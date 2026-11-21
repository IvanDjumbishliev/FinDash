import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pymupdf
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils.timezone import now
from rest_framework.test import APIClient

from api.models import StatementImport, Transaction

PREVIEW = "/api/bank-statement/preview/"


class StatementImportTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user(username="synthetic-import-owner")
        self.other = users.objects.create_user(username="synthetic-import-other")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def csv(self, text, **options):
        return self.client.post(PREVIEW, {
            "file": SimpleUploadedFile("statement.csv", text, content_type="text/csv"),
            **options,
        }, format="multipart")

    def pdf(self, lines, path=PREVIEW, **options):
        with pymupdf.open() as document:
            page = document.new_page()
            for index, line in enumerate(lines, 1):
                page.insert_text((30, 24 * index), line)
            data = document.tobytes()
        return self.client.post(path, {
            "file": SimpleUploadedFile("statement.pdf", data, content_type="application/pdf"),
            **options,
        }, format="multipart")

    def detail(self, result):
        return f"/api/bank-statement/imports/{result.data['id']}/"

    def test_european_csv_preview_then_idempotent_confirmation(self):
        response = self.csv(
            "Дата;Описание;Дебит;Кредит;Валута\n"
            '21.11.2026;"Synthetic market; test";1.234,56;;EUR\n'
            "22/11/2026;Synthetic refund;;12,50;€\n".encode("utf-8-sig")
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], "ready")
        self.assertEqual([row["amount"] for row in response.data["transactions"]], ["-1234.56", "12.50"])
        self.assertEqual(response.data["row_count"], 2)
        self.assertFalse(Transaction.objects.exists())
        url = self.detail(response)
        self.assertEqual(self.client.get(url).data["status"], "ready")
        for _ in range(2):
            completed = self.client.post(f"{url}confirm/")
            self.assertEqual(completed.status_code, 200, completed.data)
            self.assertEqual(completed.data["status"], "imported")
            self.assertEqual(completed.data["transactions"], [])
        self.assertEqual(Transaction.objects.filter(user=self.owner).count(), 2)
        self.assertEqual(StatementImport.objects.get(pk=response.data["id"]).parsed_rows, [])

    def test_custom_headers_mapping_date_order_and_currency(self):
        text = 'Booked,Payee label,Net,Indicator\n11/22/2026,Test merchant,"1,234.75",DR\n'.encode()
        unknown = self.csv(text)
        self.assertEqual(unknown.data["status"], "needs_mapping")
        self.assertEqual(tuple(unknown.data["columns"]), ("Booked", "Payee label", "Net", "Indicator"))
        response = self.csv(text, mapping=json.dumps({
            "date": "Booked", "description": "Payee label", "amount": "Net", "direction": "Indicator",
        }), date_order="MDY", default_currency="gbp")
        self.assertEqual(response.status_code, 201, response.data)
        row, = response.data["transactions"]
        self.assertEqual(row["timestamp"], "2026-11-22T00:00:00+00:00")
        self.assertEqual(row["amount"], "-1234.75")
        self.assertEqual(row["currency"], "GBP")

    def test_amounts_handle_grouped_separators_sign_indicators_and_embedded_symbols(self):
        response = self.csv(
            "Date\tDescription\tAmount\n"
            "2026-11-21\tSynthetic parentheses\t(€ 1\u202f234,50)\n"
            "2026-11-22\tSynthetic trailing debit\t2,25-\n"
            "2026-11-23\tSynthetic credit\t5.80 GBP CR\n".encode("utf-16"),
            default_currency="EUR",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual([(row["amount"], row["currency"]) for row in response.data["transactions"]], [
            ("-1234.50", "EUR"), ("-2.25", "EUR"), ("5.80", "GBP"),
        ])

    def test_parsing_errors_are_recorded_without_partial_writes_or_echoing_values(self):
        response = self.csv(b"Date,Description,Amount,Currency\n2026-11-10,Test,-3,USD\nbad,private-example,10,USD\n")
        self.assertEqual(response.status_code, 422, response.data)
        self.assertEqual(response.data["status"], "failed")
        self.assertEqual(response.data["errors"][0]["row"], 3)
        self.assertNotIn("private-example", str(response.data))
        self.assertEqual(StatementImport.objects.get(pk=response.data["id"]).parsed_rows, [])
        self.assertEqual(self.client.post(f"{self.detail(response)}confirm/").status_code, 409)
        self.assertFalse(Transaction.objects.exists())

    def test_extension_mime_signature_size_and_csv_structure(self):
        for filename, mime, content, expected in [
            ("file.xlsx", "application/octet-stream", b"not a file", 415),
            ("file.csv", "application/pdf", b"Date,Description,Amount", 415),
            ("file.csv", "text/csv", b"PK\x03\x04Zip", 415),
            ("file.csv", "text/csv", b'Date,Description,Amount\n2026-11-21,"unclosed,10', 400),
            ("file.pdf", "application/pdf", b"not a pdf", 400),
        ]:
            with self.subTest(filename=filename, mime=mime, expected=expected):
                response = self.client.post(PREVIEW, {
                    "file": SimpleUploadedFile(filename, content, content_type=mime),
                }, format="multipart")
                self.assertEqual(response.status_code, expected, response.data)
                self.assertEqual(response.data["status"], "failed")
        with patch("api.services.statements.pipeline.MAX_FILE_BYTES", 32):
            response = self.csv(b"Date,Description,Amount,Currency\n" + b"a" * 500)
        self.assertEqual(response.status_code, 413, response.data)

    @override_settings(API_KEY="")
    @patch("api.services.statements.pdf_parser.client")
    def test_pdf_local_preview_and_legacy_direct_route_work_without_gemini(self, client):
        lines = ["Date;Description;Debit;Credit;Currency", "21.11.2026;Synthetic market;12,50;;EUR"]
        preview = self.pdf(lines)
        self.assertEqual(preview.status_code, 201, preview.data)
        self.assertEqual(preview.data["transactions"][0]["amount"], "-12.50")
        self.assertFalse(Transaction.objects.exists())
        legacy = self.pdf(lines, "/api/bank-statement/")
        self.assertEqual(legacy.status_code, 201, legacy.data)
        self.assertEqual(Transaction.objects.count(), 1)
        client.models.generate_content.assert_not_called()

    @override_settings(API_KEY="test-key")
    @patch("api.services.statements.pdf_parser.client")
    def test_pdf_fallback_requires_consent_and_rejects_invalid_gemini_rows(self, client):
        lines = ["Synthetic unsupported layout"]
        local = self.pdf(lines)
        self.assertEqual(local.status_code, 422)
        self.assertEqual(local.data["code"], "external_processing_required")
        client.models.generate_content.assert_not_called()
        client.models.generate_content.return_value = SimpleNamespace(text='[{"amount": -10.00}]')
        remote = self.pdf(lines, allow_external_processing="true")
        self.assertEqual(remote.status_code, 422, remote.data)
        client.models.generate_content.assert_called_once()
        client.files.upload.assert_not_called()
        self.assertFalse(Transaction.objects.exists())

    def test_owner_scope_discard_and_expiration(self):
        statement = b"Date,Description,Amount,Currency\n2026-11-21,Purchase,-100,EUR\n"
        response = self.csv(statement)
        url = self.detail(response)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(f"{url}confirm/").status_code, 404)
        self.assertEqual(self.client.delete(url).status_code, 404)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.delete(url).data["status"], "discarded")
        self.assertEqual(self.client.post(f"{url}confirm/").status_code, 409)

        stale = self.csv(statement)
        StatementImport.objects.filter(pk=stale.data["id"]).update(expires_at=now() - timedelta(seconds=1))
        call_command("expire_statement_previews")
        result = self.client.get(self.detail(stale)).data
        self.assertEqual(result["status"], "expired")
        self.assertEqual(result["transactions"], [])
