import hashlib
import json
from hmac import compare_digest

from django.core import signing
from django.db import DatabaseError
from django.http import HttpResponse
from rest_framework import serializers
from rest_framework.response import Response

from api.services.budgets import parse_month
from api.services.copilot_tools import DataLimitExceeded, currency_code
from api.services.notification_events import report_generated
from api.services.notifications import after_commit
from api.services.report_explanation import explain_report
from api.services.report_pdf import render_report_pdf
from api.services.reports import generate_report, report_tools

from .assistant import PrivateCopilotView, StrictBooleanField

EXPORT_SALT = "findash.monthly-report.export.v1"
EXPORT_MAX_AGE = 3600
EXPORT_MAX_BYTES = 65536


class ReportInput(serializers.Serializer):
    month = serializers.RegexField(r"\A[0-9]{4}-[0-9]{2}\Z", required=False)
    currency = serializers.RegexField(r"\A[A-Za-z]{3}\Z", required=False)
    ai_consent = StrictBooleanField(default=False)

    def validate_month(self, value):
        try:
            month = parse_month(value)
        except ValueError as error:
            raise serializers.ValidationError(str(error)) from error
        if not 2 <= month.year <= 9998:
            raise serializers.ValidationError("Choose a month with representable timezone boundaries.")
        return month

    def validate_currency(self, value):
        return value.upper()


class ReportExportInput(serializers.Serializer):
    report = serializers.DictField()
    export_token = serializers.CharField(max_length=1024)


def report_digest(report):
    payload = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    if len(payload) > EXPORT_MAX_BYTES:
        raise serializers.ValidationError({"report": "The report exceeds the export size limit."})
    return hashlib.sha256(payload).hexdigest()


class FinancialReportView(PrivateCopilotView):
    def post(self, request):
        serializer = ReportInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            tools, generated_at = report_tools(request.user)
            month = data.get("month", tools.today.replace(day=1))
            if month > tools.today.replace(day=1):
                raise serializers.ValidationError({"month": "Choose the current month or an earlier month."})
            profile = getattr(request.user, "userprofile", None)
            currency = data.get("currency") or (currency_code(profile.currency) if profile else None) or "USD"
            report = generate_report(request.user, tools, month, currency, generated_at=generated_at)
            report["ai"] = explain_report(request.user, report, consent=data["ai_consent"])
        except DataLimitExceeded:
            return Response({"error": "There are too many transactions to generate this report."}, status=422)
        except DatabaseError:
            return Response({"error": "Financial records are temporarily unavailable."}, status=503)
        token = signing.dumps({"owner": request.user.pk, "digest": report_digest(report)}, salt=EXPORT_SALT)
        after_commit(report_generated, request.user.pk, month.isoformat(), currency, tools.today)
        return Response({"report": report, "export_token": token})


class FinancialReportPDFView(PrivateCopilotView):
    def post(self, request):
        serializer = ReportExportInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        report = serializer.validated_data["report"]
        try:
            token = signing.loads(
                serializer.validated_data["export_token"], salt=EXPORT_SALT, max_age=EXPORT_MAX_AGE,
            )
        except signing.BadSignature:
            return Response({"error": "Generate a fresh report before exporting."}, status=400)
        if token["owner"] != request.user.pk:
            return Response({"error": "Report not found."}, status=404)
        if not compare_digest(token["digest"], report_digest(report)):
            return Response({"error": "The report changed. Generate a fresh preview."}, status=400)

        try:
            pdf = render_report_pdf(report)
        except (ValueError, RuntimeError):
            return Response({"error": "PDF rendering is temporarily unavailable."}, status=503)
        filename = f"findash-report-{report['period']['month']}-{report['currency']}.pdf"
        return HttpResponse(pdf, content_type="application/pdf", headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        })
