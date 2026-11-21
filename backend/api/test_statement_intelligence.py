import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from api.models import MerchantCategoryRule, StatementImport, Transaction

BASE = "/api/bank-statement/"
HEADER = "Date,Description,Amount,Currency,Reference\n"


class StatementIntelligenceTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="import-review-owner")
        self.other = get_user_model().objects.create_user(username="import-review-other")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def preview(self, text, **options):
        response = self.client.post(f"{BASE}preview/", {
            "file": SimpleUploadedFile("synthetic.csv", text.encode(), content_type="text/csv"),
            **options,
        }, format="multipart")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def detail(self, preview):
        return f"{BASE}imports/{preview['id']}/"

    def review(self, preview, changes):
        return self.client.patch(self.detail(preview), {
            "revision": preview["revision"], "changes": changes,
        }, format="json")

    def confirm(self, preview):
        return self.client.post(self.detail(preview) + "confirm/", {"revision": preview["revision"]}, format="json")

    def existing(self, **overrides):
        fields = {
            "user": self.owner, "amount": Decimal("-12.00"), "currency": "EUR",
            "particulars": "POS Lidl REF: NY-1001", "category": "shopping",
            "timestamp": datetime(2026, 11, 21, 14, tzinfo=timezone.utc),
        }
        return Transaction.objects.create(**{**fields, **overrides})

    def test_normalized_merchant_and_rule_precedence_are_owner_scoped(self):
        MerchantCategoryRule.objects.create(
            owner=self.other, merchant="Lidl", normalized_merchant="lidl", category="travel",
        )
        initial = self.preview(HEADER + "21.11.2026,POS Lidl.com REF: XY-1001,-12,EUR,\n")
        row, = initial["transactions"]
        self.assertEqual(row["normalized_merchant"], "lidl")
        self.assertEqual(row["reference"], "XY-1001")
        self.assertEqual(row["category"], "groceries")
        self.assertEqual(row["category_source"], "built_in_rule")
        self.assertEqual(row["category_confidence"], 0.8)

        rule = self.client.post(f"{BASE}rules/", {"merchant": "LIDL.com 4321", "category": "bills"}, format="json")
        self.assertEqual(rule.status_code, 201, rule.data)
        self.assertEqual(self.client.post(f"{BASE}rules/", {"merchant": "Lidl", "category": "travel"}, format="json").status_code, 400)
        mapped = self.preview(HEADER + "21.11.2026,Lidl,-12,EUR,XY-2001\n")
        row, = mapped["transactions"]
        self.assertEqual((row["category"], row["category_source"], row["category_confidence"]), ("bills", "user_rule", 1.0))
        url = f"{BASE}rules/{rule.data['id']}/"
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.delete(url).status_code, 404)
        self.client.force_authenticate(self.owner)
        updated = self.client.patch(url, {"category": "shopping"}, format="json")
        self.assertEqual(updated.data["category"], "shopping")
        self.assertEqual(self.client.delete(url).status_code, 204)

    def test_duplicate_checks_use_all_dimensions_and_refs(self):
        stored = self.existing()
        self.existing(user=self.other, particulars="Synthetic distinct merchant")
        preview = self.preview(HEADER +
            "21.11.2026,LIDL.com,-12,EUR,NY1001\n"  # existing
            "21.11.2026,LIDL,-12,EUR,NY1002\n"  # distinct printed reference
            "22.11.2026,LIDL,-12,EUR,NY1001\n"  # distinct date
            "21.11.2026,LIDL,12,EUR,NY1001\n"  # distinct direction
            "21.11.2026,LIDL,-12,USD,NY1001\n"  # distinct currency
            "21.11.2026,Synthetic distinct merchant,-12,EUR,NY1001\n"  # distinct merchant, no cross-user match
            "21.11.2026,LIDL,-12,EUR,NY1002\n"  # within-file
        )
        rows = preview["transactions"]
        self.assertEqual(rows[0]["duplicate_matches"]["existing"], [stored.pk])
        self.assertEqual(rows[0]["decision"], "pending")
        self.assertEqual([row["decision"] for row in rows[1:6]], ["approved"] * 5)
        self.assertEqual(rows[6]["duplicate_matches"]["file"], [2])
        self.assertEqual(rows[6]["decision"], "pending")

    def test_correction_and_bulk_approval_rejection_commit_and_history(self):
        self.existing()
        preview = self.preview(HEADER +
            "21.11.2026,Lidl,-12,EUR,NY1001\n"
            "21.11.2026,Test vendor,-8,EUR,AB1111\n"
            "21.11.2026,Other synthetic merchant,-9,EUR,AB1112\n"
        )
        self.assertEqual(self.review(preview, [{"row_id": 1, "decision": "approved"}]).status_code, 409)
        result = self.review(preview, [
            {"row_id": 1, "decision": "approved", "allow_duplicate": True},
            {"row_id": 2, "merchant": "Corrected Vendor", "category": "bills", "decision": "approved"},
            {"row_id": 3, "decision": "rejected"},
        ])
        self.assertEqual(result.status_code, 200, result.data)
        reviewed = result.data
        self.assertEqual(reviewed["transactions"][1]["category_source"], "manual")
        self.assertEqual(self.review(preview, [{"row_id": 2, "category": "finance"}]).status_code, 409)
        self.assertEqual(self.confirm(preview).status_code, 409)
        committed = self.confirm(reviewed)
        self.assertEqual(committed.status_code, 200, committed.data)
        self.assertEqual(committed.data["imported_count"], 2)
        self.assertEqual(self.confirm(reviewed).data["imported_count"], 2)
        saved = Transaction.objects.get(merchant="Corrected Vendor")
        self.assertEqual((saved.category, saved.particulars, saved.statement_reference), ("bills", "Test vendor", "AB1111"))
        self.assertEqual(str(saved.statement_import_id), preview["id"])
        history = self.client.get(f"{BASE}imports/").data["results"]
        self.assertEqual((history[0]["row_count"], history[0]["imported_count"]), (3, 2))
        self.assertNotIn("transactions", history[0])
        url = f"{self.detail(preview)}transactions/"
        self.assertEqual(self.client.get(url).data["count"], 2)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get(f"{BASE}imports/").data["results"], [])
        self.assertEqual(self.review(reviewed, [{"row_id": 2, "category": "finance"}]).status_code, 404)

    def test_confirmation_rechecks_duplicates_from_another_preview(self):
        text = HEADER + "21.11.2026,Test merchant,-12,EUR,\n"
        first = self.preview(text)
        second = self.preview(text)
        self.assertEqual(self.confirm(first).status_code, 200)
        response = self.confirm(second)
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data["status"], "ready")
        self.assertEqual(response.data["transactions"][0]["decision"], "pending")
        self.assertEqual(Transaction.objects.count(), 1)
        reviewed = self.review(response.data, [{"row_id": 1, "decision": "rejected"}])
        self.assertEqual(reviewed.status_code, 200)
        self.assertEqual(self.confirm(reviewed.data).status_code, 409)

    @override_settings(API_KEY="synthetic-configured-key")
    @patch("api.services.statements.intelligence.client")
    def test_ai_defaults_off_validates_response_and_requires_review(self, client):
        text = HEADER + "21.11.2026,Synthetic outfit REF: XY1001,-30,EUR,\n"
        self.assertEqual(self.preview(text)["ai_status"], "not_requested")
        client.models.generate_content.assert_not_called()
        client.models.generate_content.return_value = SimpleNamespace(text='[{"index":0,"category":"not-a-category"}]')
        bad = self.preview(text, allow_ai_categorization="true")
        self.assertEqual(bad["ai_status"], "unavailable")
        self.assertEqual(bad["transactions"][0]["category"], "general")
        client.models.generate_content.return_value = SimpleNamespace(text='[{"index":0,"category":"shopping"}]')
        result = self.preview(text, allow_ai_categorization="true")
        row, = result["transactions"]
        self.assertEqual((row["category"], row["category_source"], row["decision"]), ("shopping", "ai", "pending"))
        outbound = client.models.generate_content.call_args.kwargs["contents"][1]
        self.assertEqual(json.loads(outbound), [{"index": 0, "merchant": "Synthetic outfit"}])
        self.assertEqual(self.confirm(result).status_code, 409)
        reviewed = self.review(result, [{"row_id": 1, "decision": "approved"}])
        self.assertEqual(self.confirm(reviewed.data).status_code, 200)

    def test_atomic_import_rolls_back_rows_and_status_on_database_error(self):
        preview = self.preview(HEADER + "21.11.2026,Synthetic vendor,-8,EUR,\n21.11.2026,Second vendor,-9,EUR,\n")

        def partial_failure(rows, **kwargs):
            rows[0].save()
            raise DatabaseError("synthetic partial write failure")

        with patch("api.services.statements.imports.Transaction.objects.bulk_create", side_effect=partial_failure):
            failed = self.confirm(preview)
        self.assertEqual(failed.status_code, 503)
        self.assertFalse(Transaction.objects.exists())
        record = StatementImport.objects.get(pk=preview["id"])
        self.assertEqual((record.status, record.revision, len(record.parsed_rows)), ("ready", 0, 2))
        self.assertEqual(self.confirm(preview).status_code, 200)
        self.assertEqual(Transaction.objects.count(), 2)

    def test_invalid_row_edits_and_duplicate_row_ids_are_rejected(self):
        preview = self.preview(HEADER + "21.11.2026,Synthetic vendor,-8,EUR,\n")
        for changes in [
            [{"row_id": 2, "decision": "rejected"}],
            [{"row_id": 1, "category": "invalid category"}],
            [{"row_id": 1, "category": "bills"}, {"row_id": 1, "decision": "rejected"}],
            [{"row_id": 1, "merchant": "1234"}],
        ]:
            self.assertEqual(self.review(preview, changes).status_code, 400)
        self.assertEqual(self.client.get(self.detail(preview)).data["revision"], 0)
