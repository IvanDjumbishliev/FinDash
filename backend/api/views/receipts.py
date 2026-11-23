from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core import signing
from django.core.files.uploadhandler import MemoryFileUploadHandler, StopUpload
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import generics, serializers
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from django.core.exceptions import TooManyFilesSent

from api.models import GroceryOffer, Receipt, ReceiptItem, Transaction
from api.services.grocery_catalog import normalized
from api.services.grocery_matching import classify
from api.services.receipts import (
    MAX_BYTES, MAX_IMAGES, MAX_ITEMS, SOFIA, ReceiptScanError, prepare_receipt_images, product_identity,
    receipt_fingerprint, scan_receipt,
)
from api.services.receipt_history import filter_receipts, matching_transactions, receipt_statistics
from api.services.statements.intelligence import merchant_identity
from api.throttles import SensitiveEndpointThrottle

from .assistant import PrivateCopilotView

PREVIEW_SALT = "findash.receipt.preview.v1"
PREVIEW_MAX_AGE = 3600


class BoundedReceiptUpload(MemoryFileUploadHandler):
    """Keep the small image in memory and place a limit on streamed bytes."""

    received = 0
    exceeded = False

    def handle_raw_input(self, input_data, META, content_length, boundary, encoding=None):
        self.activated = True

    def receive_data_chunk(self, raw_data, start):
        self.received += len(raw_data)
        if self.received > MAX_BYTES:
            self.exceeded = True
            raise StopUpload()
        return super().receive_data_chunk(raw_data, start)


class ReceiptPreviewUploadSerializer(serializers.Serializer):
    file = serializers.ListField(child=serializers.FileField(), min_length=1, max_length=MAX_IMAGES)
    source = serializers.ChoiceField(choices=Receipt.Source.choices, default=Receipt.Source.UPLOAD)
    date_order = serializers.ChoiceField(choices=["DMY", "MDY"], default="DMY")
    allow_ai = serializers.ChoiceField(choices=["true", "false"], default="false")


class ReceiptPreviewSerializer(serializers.Serializer):
    token = serializers.CharField(allow_null=True)
    receipt = serializers.DictField(allow_null=True)
    duplicate_id = serializers.UUIDField(allow_null=True)
    possible_duplicate_ids = serializers.ListField(child=serializers.UUIDField())
    ai_status = serializers.ChoiceField(choices=["not_requested", "not_configured", "unavailable", "used"])
    status = serializers.ChoiceField(choices=["review_required", "duplicate"])


class ReviewedReceiptItemSerializer(serializers.ModelSerializer):
    # Resolve selected public catalog IDs in one query at confirmation.
    product = serializers.IntegerField(source="product_id", min_value=1, max_value=2**63 - 1, required=False, allow_null=True)
    confidence = serializers.DecimalField(
        max_digits=3, decimal_places=2, min_value=Decimal("0"), max_value=Decimal("1"),
        required=False, allow_null=True,
    )

    class Meta:
        model = ReceiptItem
        read_only_fields = ["normalized_name"]
        fields = (
            "id", "original_description", "normalized_name", "quantity", "unit", "unit_price", "line_total",
            "discount", "category", "brand", "confidence", "product",
        )

    def validate_original_description(self, value):
        if not normalized(value) or not value.isprintable():
            raise ValidationError("Enter a valid item description.")
        return value

    def validate(self, attrs):
        if attrs.get("quantity") == 0:
            raise ValidationError({"quantity": "Quantity cannot be zero."})
        if attrs.get("quantity") is None and attrs.get("unit"):
            raise ValidationError({"unit": "A measurement unit requires a quantity."})
        return attrs


class ReceiptSerializer(serializers.ModelSerializer):
    items = ReviewedReceiptItemSerializer(many=True, read_only=True)
    reconciliation_valid = serializers.SerializerMethodField()
    transaction = serializers.SerializerMethodField()

    class Meta:
        model = Receipt
        fields = (
            "id", "merchant", "normalized_merchant", "purchased_at", "currency", "subtotal", "discounts",
            "tax_total", "total", "reference", "status", "source", "transaction", "reconciliation_valid",
            "created_at", "updated_at", "items",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_transaction(self, receipt):
        payment = receipt.transaction
        return payment.pk if payment and payment.user_id == receipt.owner_id else None

    @extend_schema_field(bool)
    def get_reconciliation_valid(self, receipt):
        payment = receipt.transaction
        return bool(payment and payment.user_id == receipt.owner_id
                    and payment.amount == -receipt.total and payment.currency.strip().upper() == receipt.currency)


class ReceiptCorrectionSerializer(serializers.ModelSerializer):
    items = ReviewedReceiptItemSerializer(many=True, allow_empty=False, max_length=MAX_ITEMS)

    class Meta:
        model = Receipt
        fields = ("merchant", "purchased_at", "currency", "subtotal", "discounts", "tax_total",
                  "total", "reference", "items")
        validators = []

    def validate_merchant(self, value):
        if not normalized(value) or not value.isprintable():
            raise ValidationError("Enter a valid merchant name.")
        return value


    def validate_purchased_at(self, value):
        if not 1900 <= value.year < 9999:
            raise ValidationError("Choose a purchase date between 1900 and 9998.")
        return value


class ExistingReceiptItemSerializer(ReviewedReceiptItemSerializer):
    id = serializers.IntegerField(min_value=1, max_value=2**63 - 1, required=False)


class ExistingReceiptCorrectionSerializer(ReceiptCorrectionSerializer):
    items = ExistingReceiptItemSerializer(many=True, allow_empty=False, max_length=MAX_ITEMS)


class ReceiptConfirmationSerializer(ReceiptCorrectionSerializer):
    token = serializers.CharField(max_length=512, write_only=True)

    class Meta(ReceiptCorrectionSerializer.Meta):
        fields = ("token", *ReceiptCorrectionSerializer.Meta.fields)


class ReceiptHistoryFilters(serializers.Serializer):
    store = serializers.CharField(max_length=120, required=False)
    product = serializers.CharField(max_length=120, required=False)
    start = serializers.DateField(required=False)
    end = serializers.DateField(required=False)

    def validate(self, attrs):
        for field in ("store", "product"):
            if field in attrs and not normalized(attrs[field]):
                raise ValidationError({field: "Enter a store or product name."})
        for field in ("start", "end"):
            if field in attrs and not 1900 <= attrs[field].year < 9999:
                raise ValidationError({field: "Choose a date between 1900 and 9998."})
        if "start" in attrs and "end" in attrs and attrs["start"] > attrs["end"]:
            raise ValidationError({"end": "End date must be on or after the start date."})
        return attrs


class ReceiptBreakdownSerializer(serializers.Serializer):
    name = serializers.CharField(allow_blank=True)
    total = serializers.CharField()
    line_count = serializers.IntegerField()


class ReceiptStatisticsSerializer(serializers.Serializer):
    currency = serializers.CharField()
    total = serializers.CharField()
    item_total = serializers.CharField()
    receipt_count = serializers.IntegerField()
    linked_count = serializers.IntegerField()
    categories = ReceiptBreakdownSerializer(many=True)
    categories_truncated = serializers.BooleanField()
    products = ReceiptBreakdownSerializer(many=True)
    products_truncated = serializers.BooleanField()


class ReceiptMatchSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    merchant = serializers.CharField()
    timestamp = serializers.DateTimeField()
    amount = serializers.CharField()
    currency = serializers.CharField()
    days_apart = serializers.IntegerField()
    merchant_match = serializers.ChoiceField(choices=["exact", "partial", "unknown"])
    confidence = serializers.ChoiceField(choices=["high", "review"])


class ReceiptReconciliationSerializer(serializers.Serializer):
    transaction = serializers.IntegerField(min_value=1, max_value=2**63 - 1, allow_null=True)


class ReceiptConflict(APIException):
    status_code = 409
    default_detail = "This payment is already linked to another receipt."


def receipt_queryset(user):
    return Receipt.objects.filter(owner=user).select_related("transaction").prefetch_related("items")


def receipt_response(request, pk, *, status=200):
    return Response(ReceiptSerializer(receipt_queryset(request.user).get(pk=pk)).data, status=status)


class ReceiptPrivateView(PrivateCopilotView):
    throttle_classes = [SensitiveEndpointThrottle]
    throttle_scope = "receipt_scan"


def possible_duplicates(receipts, preview):
    if not all(preview.get(field) for field in ("merchant", "currency", "purchase_date")) or preview["total"] is None:
        return []
    merchant, identity = merchant_identity(preview["merchant"])
    day = date.fromisoformat(preview["purchase_date"])
    if not 1900 <= day.year < 9999:
        return []
    starts = datetime.combine(day, time.min, tzinfo=SOFIA)
    return list(receipts.filter(
        normalized_merchant=identity or normalized(merchant),
        currency=preview["currency"], total=preview["total"],
        purchased_at__gte=starts, purchased_at__lt=starts + timedelta(days=1),
    ).values_list("pk", flat=True)[:5])


class ReceiptPreviewView(ReceiptPrivateView):
    parser_classes = [MultiPartParser]

    @extend_schema(request=ReceiptPreviewUploadSerializer, responses=ReceiptPreviewSerializer)
    def post(self, request):
        handler = BoundedReceiptUpload(request._request)
        request._request.upload_handlers = [handler]
        try:
            payload = request.data
        except TooManyFilesSent as error:
            raise ValidationError({"file": "Upload up to three receipt images."}) from error
        if handler.exceeded:
            return Response({"detail": "Receipt images must total 8 MB or smaller."}, status=413)
        files = request.FILES.getlist("file")
        if len(request.FILES) != 1 or not files:
            raise ValidationError({"file": "Upload receipt images using the file field."})
        if any(len(payload.getlist(field)) > 1 or field in request.FILES for field in ("allow_ai", "date_order", "source")):
            raise ValidationError("Provide one value for each scan option.")
        options = {field: payload[field] for field in ("allow_ai", "date_order", "source") if field in payload}
        upload = ReceiptPreviewUploadSerializer(data={**options, "file": files})
        upload.is_valid(raise_exception=True)
        source = upload.validated_data
        try:
            digest, pages = prepare_receipt_images(source["file"])
            owner_receipts = Receipt.objects.filter(owner=request.user)
            duplicate = owner_receipts.filter(image_digest=digest).values_list("pk", flat=True).first()
            scanned, ai_status = (None, "not_requested") if duplicate else scan_receipt(
                pages, date_order=source["date_order"], consent=source["allow_ai"] == "true",
            )
        except ReceiptScanError as error:
            return Response({"detail": str(error)}, status=error.status)
        token = None if duplicate else signing.dumps(
            {"owner": request.user.pk, "digest": digest, "source": source["source"]}, salt=PREVIEW_SALT,
        )
        return Response({
            "token": token, "receipt": scanned, "duplicate_id": duplicate,
            "possible_duplicate_ids": possible_duplicates(owner_receipts, scanned) if scanned else [],
            "ai_status": ai_status,
            "status": "duplicate" if duplicate else "review_required",
        })


def build_receipt_items(items):
    products = GroceryOffer.objects.in_bulk({item["product_id"] for item in items if item.get("product_id")})
    rows = []
    for item in items:
        product_id = item.pop("product_id", None)
        product = products.get(product_id)
        if product_id and product is None:
            raise ValidationError({"items": "A selected catalog product no longer exists."})
        name = product_identity(item["original_description"])
        suggested_category, _, _ = classify(name, "")
        item["category"] = item.get("category") or (product.category if product else "") or suggested_category
        item["brand"] = item.get("brand") or (product.brand if product else "")
        rows.append(ReceiptItem(**item, normalized_name=name, product=product))
    return rows


class ReceiptConfirmationView(ReceiptPrivateView):
    @extend_schema(request=ReceiptConfirmationSerializer, responses={200: ReceiptSerializer, 201: ReceiptSerializer})
    def post(self, request):
        form = ReceiptConfirmationSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        details = dict(form.validated_data)
        try:
            preview = signing.loads(details.pop("token"), salt=PREVIEW_SALT, max_age=PREVIEW_MAX_AGE)
        except signing.BadSignature as error:
            raise ValidationError({"token": "This preview is invalid or has expired. Scan the receipt again."}) from error
        if preview["owner"] != request.user.pk:
            raise ValidationError({"token": "This preview is invalid or has expired. Scan the receipt again."})

        items = details.pop("items")
        merchant, fingerprint = receipt_fingerprint(details, items)
        owner_receipts = Receipt.objects.filter(owner=request.user)
        duplicate = Q(image_digest=preview["digest"]) | Q(fingerprint=fingerprint)
        if existing := owner_receipts.filter(duplicate).first():
            return receipt_response(request, existing.pk)
        rows = build_receipt_items(items)
        try:
            with transaction.atomic():
                new_receipt = owner_receipts.create(
                    **details, owner=request.user, normalized_merchant=merchant, image_digest=preview["digest"],
                    fingerprint=fingerprint, source=preview["source"],
                )
                for row in rows:
                    row.receipt = new_receipt
                ReceiptItem.objects.bulk_create(rows)
        except IntegrityError:
            existing = owner_receipts.filter(duplicate).first()
            if existing is None:
                raise
            return receipt_response(request, existing.pk)
        return receipt_response(request, new_receipt.pk, status=201)


class ReceiptPagination(PageNumberPagination):
    page_size = 20


class ReceiptListView(PrivateCopilotView, generics.ListAPIView):
    serializer_class = ReceiptSerializer
    pagination_class = ReceiptPagination
    queryset = Receipt.objects.none()

    @extend_schema(parameters=[ReceiptHistoryFilters])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        return filter_receipts(receipt_queryset(self.request.user), history_filters(self.request))


def history_filters(request):
    form = ReceiptHistoryFilters(data=request.query_params)
    form.is_valid(raise_exception=True)
    return form.validated_data


class ReceiptStatisticsView(PrivateCopilotView):
    @extend_schema(parameters=[ReceiptHistoryFilters], responses=ReceiptStatisticsSerializer(many=True))
    def get(self, request):
        queryset = filter_receipts(Receipt.objects.filter(owner=request.user), history_filters(request))
        return Response(receipt_statistics(queryset))


class ReceiptDetailView(PrivateCopilotView, generics.RetrieveDestroyAPIView):
    serializer_class = ReceiptSerializer
    queryset = Receipt.objects.none()

    def get_queryset(self):
        return receipt_queryset(self.request.user)

    @extend_schema(request=ExistingReceiptCorrectionSerializer, responses=ReceiptSerializer)
    def patch(self, request, pk):
        form = ExistingReceiptCorrectionSerializer(data=request.data, partial=True)
        form.is_valid(raise_exception=True)
        details = dict(form.validated_data)
        corrected_items = details.pop("items", None)
        if corrected_items is not None:
            item_form = ExistingReceiptItemSerializer(data=request.data["items"], many=True, allow_empty=False, max_length=MAX_ITEMS)
            item_form.is_valid(raise_exception=True)
            corrected_items = item_form.validated_data
        try:
            with transaction.atomic():
                receipt = get_object_or_404(Receipt.objects.select_for_update(), owner=request.user, pk=pk)
                for key, value in details.items():
                    setattr(receipt, key, value)
                identity = {key: getattr(receipt, key) for key in ("merchant", "purchased_at", "currency", "total", "reference")}
                items = corrected_items if corrected_items is not None else list(
                    receipt.items.values("original_description", "line_total"),
                )
                receipt.normalized_merchant, receipt.fingerprint = receipt_fingerprint(identity, items)
                if Receipt.objects.filter(owner=request.user, fingerprint=receipt.fingerprint).exclude(pk=pk).exists():
                    raise ReceiptConflict("These corrections match an existing receipt.")
                if receipt.transaction_id and {"currency", "total"} & details.keys():
                    if not ReceiptSerializer().get_reconciliation_valid(receipt):
                        receipt.transaction = None
                receipt.save(update_fields=[*details, "normalized_merchant", "fingerprint", "transaction", "updated_at"])
                if corrected_items is not None:
                    rows = build_receipt_items(corrected_items)
                    existing_ids = [row.pk for row in rows if row.pk is not None]
                    if len(set(existing_ids)) != len(existing_ids) or receipt.items.filter(pk__in=existing_ids).count() != len(existing_ids):
                        raise ValidationError({"items": "Each existing item ID must belong to this receipt and appear once."})
                    for row in rows:
                        row.receipt = receipt
                    receipt.items.exclude(pk__in=existing_ids).delete()
                    ReceiptItem.objects.bulk_update(
                        [row for row in rows if row.pk is not None],
                        [field.name for field in ReceiptItem._meta.concrete_fields if not field.primary_key and field.name != "receipt"],
                    )
                    ReceiptItem.objects.bulk_create([row for row in rows if row.pk is None])
        except IntegrityError as error:
            raise ReceiptConflict("The receipt could not be updated because a conflicting change was saved.") from error
        return receipt_response(request, pk)


class ReceiptReconciliationView(PrivateCopilotView):
    @extend_schema(responses=ReceiptMatchSerializer(many=True))
    def get(self, request, pk):
        receipt = get_object_or_404(Receipt, owner=request.user, pk=pk)
        return Response(ReceiptMatchSerializer(matching_transactions(receipt), many=True).data)

    @extend_schema(request=ReceiptReconciliationSerializer, responses=ReceiptSerializer)
    def patch(self, request, pk):
        form = ReceiptReconciliationSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        payment_id = form.validated_data["transaction"]
        try:
            with transaction.atomic():
                receipt = get_object_or_404(Receipt.objects.select_for_update(), owner=request.user, pk=pk)
                if payment_id is not None:
                    payment = get_object_or_404(Transaction.objects.select_for_update(), user=request.user, pk=payment_id)
                    if payment.amount != -receipt.total or payment.currency.strip().upper() != receipt.currency:
                        raise ValidationError({"transaction": "Choose a payment with the same currency and matching signed amount."})
                    if Receipt.objects.filter(transaction=payment).exclude(pk=pk).exists():
                        raise ReceiptConflict()
                receipt.transaction_id = payment_id
                receipt.save(update_fields=["transaction", "updated_at"])
        except IntegrityError as error:
            raise ReceiptConflict() from error
        return receipt_response(request, pk)
