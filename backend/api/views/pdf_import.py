from django.db import DatabaseError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.throttles import SensitiveEndpointThrottle
from api.models import StatementImport
from api.services.statements.imports import PREVIEW_LIFETIME, confirm_import, expire_previews, preview_rows, review_import
from api.services.statements.intelligence import prepare_rows
from api.services.statements.normalization import StatementError
from api.services.statements.pipeline import PARSERS, StatementSizeLimit, parse_options, upload_content

from .statement_review import ConfirmationSerializer, ReviewRequestSerializer


def import_data(record, *, include_rows=True):
    return {
        "id": str(record.pk),
        "file_format": record.file_format,
        "status": record.status,
        "row_count": record.row_count,
        "imported_count": (
            record.imported_count if record.imported_count is not None else
            record.row_count if record.status == StatementImport.Status.IMPORTED else 0
        ),
        "revision": record.revision,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        **({"transactions": preview_rows(record)} if include_rows else {}),
        "errors": record.errors,
        "expires_at": record.expires_at.isoformat(),
    }


class StatementUploadView(APIView):
    throttle_classes = [SensitiveEndpointThrottle]
    throttle_scope = "statement_upload"

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    allowed_formats = frozenset(PARSERS)
    legacy_commit = False

    def post(self, request):
        expire_previews(request.user)
        limiter = StatementSizeLimit(request._request)
        request._request.upload_handlers.insert(0, limiter)
        file_format = ""
        parsed = None
        try:
            files = [upload for _, uploads in request.FILES.lists() for upload in uploads]
            if limiter.exceeded:
                raise StatementError("Statements must be 10 MB or smaller.", status=413)
            if len(files) != 1 or request.FILES.get("file") is None:
                raise StatementError("Upload exactly one statement using the file field.")
            file_format, content = upload_content(files[0], allowed_formats=self.allowed_formats)
            options = parse_options(request.data)
            parsed = PARSERS[file_format].parse(content, options)
        except StatementError as error:
            failed = self.create_import(request.user, file_format, StatementImport.Status.FAILED, errors=[{"message": str(error)}])
            response = {**import_data(failed), "error": str(error)}
            if error.code:
                response["code"] = error.code
            return Response(response, status=error.status)

        result_status = StatementImport.Status.READY
        if parsed.needs_mapping:
            result_status = StatementImport.Status.NEEDS_MAPPING
        elif parsed.errors:
            result_status = StatementImport.Status.FAILED
        rows, ai_status = (
            prepare_rows(request.user, parsed.rows, ai_consent=options.allow_ai_categorization)
            if result_status == StatementImport.Status.READY else ([], "not_requested")
        )
        record = self.create_import(
            request.user, file_format, result_status,
            errors=parsed.errors, rows=rows,
        )
        data = {**import_data(record), "ai_status": ai_status}
        if parsed.columns and not self.legacy_commit and file_format == "csv":
            data.update(columns=parsed.columns, mapping=parsed.mapping)
        if result_status == StatementImport.Status.NEEDS_MAPPING:
            return Response({**data, "error": "Map the date, description, and amount or debit/credit columns."})
        if result_status == StatementImport.Status.FAILED:
            return Response({**data, "error": "Fix the invalid transaction rows before importing."}, status=422)
        if self.legacy_commit:
            if any(row["decision"] != "approved" for row in rows):
                return Response({**data, "error": "Review this statement before importing flagged transactions."}, status=409)
            try:
                saved = confirm_import(record)
            except StatementError as error:
                return Response({**data, "error": str(error)}, status=error.status)
            except DatabaseError:
                return Response({**data, "error": "The statement could not be saved."}, status=503)
            if saved.status != StatementImport.Status.IMPORTED:
                return Response({**import_data(saved), "error": "Review newly flagged transactions."}, status=409)
            return Response({"response": [{key: row[key] for key in
                ("amount", "timestamp", "category", "particulars", "currency")} for row in rows]}, status=201)
        return Response(data, status=201)

    @staticmethod
    def create_import(owner, file_format, status, *, errors=None, rows=None):
        return StatementImport.objects.create(
            owner=owner, file_format=file_format, status=status,
            errors=errors or [], parsed_rows=rows or [], row_count=len(rows or []),
            expires_at=timezone.now() + PREVIEW_LIFETIME,
        )


class UploadBankStatementView(StatementUploadView):
    """Compatibility endpoint for clients that explicitly submit direct PDF imports."""

    allowed_formats = {"pdf"}
    legacy_commit = True


class StatementImportDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def owned_record(request, pk):
        expire_previews(request.user)
        return get_object_or_404(StatementImport, pk=pk, owner=request.user)

    def get(self, request, pk):
        return Response(import_data(self.owned_record(request, pk)))

    def patch(self, request, pk):
        record = self.owned_record(request, pk)
        serializer = ReviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            return Response(import_data(review_import(record, **serializer.validated_data)))
        except StatementError as error:
            record.refresh_from_db()
            return Response({**import_data(record), "error": str(error)}, status=error.status)

    def delete(self, request, pk):
        record = self.owned_record(request, pk)
        StatementImport.objects.filter(pk=record.pk, owner=request.user, status__in=[
            StatementImport.Status.READY, StatementImport.Status.NEEDS_MAPPING,
        ]).update(status=StatementImport.Status.DISCARDED, parsed_rows=[], updated_at=timezone.now())
        record.refresh_from_db()
        return Response(import_data(record))


class StatementConfirmView(StatementImportDetailView):
    http_method_names = ["post", "options"]

    def post(self, request, pk):
        record = self.owned_record(request, pk)
        serializer = ConfirmationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            saved = confirm_import(record, **serializer.validated_data)
            if saved.status != StatementImport.Status.IMPORTED:
                return Response({**import_data(saved), "error": "New duplicate matches were found. Review them before confirming."}, status=409)
            return Response(import_data(saved))
        except StatementError as error:
            record.refresh_from_db()
            return Response({**import_data(record), "error": str(error)}, status=error.status)
        except DatabaseError:
            return Response({"error": "The statement could not be saved. Try again."}, status=503)


class StatementHistoryPagination(LimitOffsetPagination):
    default_limit = 25
    max_limit = 100


class StatementHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        expire_previews(request.user)
        imports = StatementImport.objects.filter(owner=request.user).defer("parsed_rows").order_by("-created_at", "-pk")
        paginator = StatementHistoryPagination()
        page = paginator.paginate_queryset(imports, request)
        return paginator.get_paginated_response([import_data(record, include_rows=False) for record in page])


class StatementImportedTransactionsView(StatementImportDetailView):
    http_method_names = ["get", "head", "options"]

    def get(self, request, pk):
        record = self.owned_record(request, pk)
        transactions = record.imported_transactions.filter(user=request.user).order_by("pk")
        paginator = StatementHistoryPagination()
        page = paginator.paginate_queryset(transactions, request)
        return paginator.get_paginated_response([
            {
                "id": row.pk, "timestamp": row.timestamp.isoformat(), "amount": str(row.amount),
                "currency": row.currency, "merchant": row.merchant or row.particulars,
                "category": row.category, "reference": row.statement_reference,
            }
            for row in page
        ])
