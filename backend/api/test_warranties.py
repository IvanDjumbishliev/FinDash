from datetime import date, datetime
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image, PngImagePlugin
from rest_framework.test import APIClient

from api.models import Notification, NotificationPreference, Receipt, ReceiptItem, Warranty, WarrantyProof
from api.services.receipts import SOFIA
from api.services.warranties import expiry_from_months, purge_warranty_data, warranty_reminders
from api.tasks import check_owner_warranties, schedule_warranties

URL = "/api/warranties/"


class WarrantyVaultTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user(username="warranty-owner")
        self.other = users.create_user(username="warranty-other")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.clock = patch("api.views.warranties.warranty_today", return_value=date(2026, 11, 23))
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def add(self, **overrides):
        data = {"product_name": "Кафемашина", "retailer": "Магазин", "purchased_on": "2026-01-31",
                "duration_months": 12, **overrides}
        response = self.client.post(URL, data, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def receipt(self, owner):
        receipt = Receipt.objects.create(
            owner=owner, merchant="Fixture Shop", purchased_at=datetime(2026, 11, 22, 22, 30, tzinfo=SOFIA),
            currency="EUR", total=10, source="upload", image_digest="receipt", fingerprint="receipt",
        )
        return ReceiptItem.objects.create(receipt=receipt, original_description="Fixture Camera",
                                          normalized_name="fixture camera", line_total=10)

    def proof(self, pk, content=None, name="proof.png"):
        if content is None:
            output = BytesIO()
            Image.new("RGB", (25, 40), "gray").save(output, format="PNG")
            content = output.getvalue()
        return self.client.post(f"{URL}{pk}/proof/", {
            "file": SimpleUploadedFile(name, content, "image/png"),
        }, format="multipart")

    def test_calendar_expiry_validation_search_and_sources(self):
        self.assertEqual(expiry_from_months(date(2024, 2, 29), 12), date(2025, 2, 28))
        warranty = self.add(duration_months=1)
        self.assertEqual(warranty["expires_on"], "2026-02-28")
        self.assertEqual(warranty["status"], "expired")
        self.assertEqual(warranty["field_sources"]["expires_on"], "calculated")
        self.assertEqual(self.client.get(URL, {"q": "КАФЕМАШИНА", "status": "expired"}).data["count"], 1)
        self.assertEqual(self.client.get(URL, {"q": "МАГАЗИН", "status": "active"}).data["count"], 0)
        detail = f"{URL}{warranty['id']}/"
        self.assertEqual(self.client.patch(detail, {"duration_months": None}, format="json").status_code, 400)
        explicit = self.client.patch(detail, {"duration_months": None, "expires_on": "2026-11-23"}, format="json")
        self.assertEqual(explicit.data["status"], "active")
        self.assertEqual(explicit.data["field_sources"]["expires_on"], "manual")
        self.assertEqual(self.client.patch(detail, {"expires_on": "2025-01-01"}, format="json").status_code, 400)

    def test_link_is_owner_scoped_and_survives_reviewed_receipt_edits(self):
        item = self.receipt(self.owner)
        other = self.receipt(self.other)
        self.assertEqual(self.client.post(URL, {"receipt_item": other.pk, "duration_months": 1}, format="json").status_code, 404)
        self.assertEqual(self.client.post(URL, {"receipt_item": item.pk}, format="json").status_code, 400)
        response = self.client.post(URL, {"receipt_item": item.pk, "duration_months": 3}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        warranty = response.data
        self.assertEqual(warranty["field_sources"]["retailer"], "receipt")
        self.assertEqual(warranty["field_sources"]["duration_months"], "manual")
        receipt_url = f"/api/receipts/{item.receipt_id}/"
        foreign_update = {"items": [{"id": other.pk, "original_description": "Foreign item", "line_total": "10"}]}
        self.assertEqual(self.client.patch(receipt_url, foreign_update, format="json").status_code, 400)
        self.assertTrue(ReceiptItem.objects.filter(pk=item.pk).exists())
        corrected = self.client.patch(receipt_url, {"items": [
            {"id": item.pk, "original_description": "Corrected Camera", "line_total": "10"},
        ]}, format="json")
        self.assertEqual(corrected.status_code, 200, corrected.data)
        self.assertEqual(corrected.data["items"][0]["id"], item.pk)
        self.assertEqual(Warranty.objects.get(pk=warranty["id"]).receipt_item_id, item.pk)
        detail = f"{URL}{warranty['id']}/"
        replacement = self.client.patch(detail, {"product_name": "My camera"}, format="json")
        self.assertEqual(replacement.data["field_sources"]["product_name"], "manual")
        self.assertEqual(self.client.delete(receipt_url).status_code, 204)
        self.assertIsNone(self.client.get(detail).data["receipt_id"])
        self.assertEqual(self.client.get(detail).data["product_name"], "My camera")

    def test_private_proof_validation_download_and_deletion(self):
        warranty = self.add()
        pk = warranty["id"]
        proof_url = f"{URL}{pk}/proof/"
        self.assertEqual(self.proof(pk, b"<script>invalid</script>").status_code, 415)
        with patch("api.views.receipts.MAX_BYTES", 64):
            self.assertEqual(self.proof(pk, b"x" * 100).status_code, 413)
        output = BytesIO()
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("Comment", "synthetic sensitive metadata")
        Image.new("RGB", (25, 40), "gray").save(output, format="PNG", pnginfo=metadata)
        self.assertEqual(self.proof(pk, output.getvalue()).status_code, 204)
        download = self.client.get(proof_url)
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download["Cache-Control"], "no-store")
        self.assertEqual(download["X-Content-Type-Options"], "nosniff")
        self.assertIn("attachment", download["Content-Disposition"])
        self.assertTrue(download.content.startswith(b"\x89PNG"))
        self.assertNotIn(b"synthetic sensitive metadata", download.content)
        with Image.open(BytesIO(download.content)) as cleaned:
            self.assertFalse(cleaned.getexif())
            self.assertFalse(cleaned.info)
        self.assertTrue(self.client.get(f"{URL}{pk}/").data["has_proof"])
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(URL).data["count"], 0)
        self.assertEqual(self.client.get(proof_url).status_code, 404)
        self.assertEqual(self.proof(pk).status_code, 404)
        self.assertEqual(self.client.delete(proof_url).status_code, 404)
        self.assertEqual(self.client.patch(f"{URL}{pk}/", {"retailer": "Unauthorized"}, format="json").status_code, 404)
        self.assertEqual(self.client.delete(f"{URL}{pk}/").status_code, 404)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.delete(proof_url).status_code, 204)
        self.assertEqual(self.client.get(proof_url).status_code, 404)
        self.assertEqual(self.proof(pk).status_code, 204)
        self.assertEqual(self.client.delete(f"{URL}{pk}/").status_code, 204)
        self.assertFalse(WarrantyProof.objects.exists())

    def test_reminders_are_opt_in_deduplicated_and_eligible_at_expiry(self):
        row = self.add(duration_months=None, expires_on="2026-12-01", reminder_days=[30, 7, 0])
        self.add()
        with patch("api.tasks.enqueue") as enqueue:
            self.assertEqual(schedule_warranties.run(), 1)
            enqueue.assert_called_once_with(check_owner_warranties, self.owner.pk)
        self.assertEqual(warranty_reminders(self.owner, today=date(2026, 11, 23)), 1)
        self.assertEqual(warranty_reminders(self.owner, today=date(2026, 11, 23)), 0)
        self.assertEqual(warranty_reminders(self.other, today=date(2026, 11, 23)), 0)
        self.assertEqual(warranty_reminders(self.owner, today=date(2026, 11, 25)), 1)
        NotificationPreference.objects.create(owner=self.owner, categories={"warranty_expiration": False})
        self.assertEqual(warranty_reminders(self.owner, today=date(2026, 12, 1)), 0)
        self.assertEqual(warranty_reminders(self.owner, today=date(2026, 12, 2)), 0)
        notice = self.client.get("/api/notifications/").data["results"][0]
        self.assertEqual(notice["payload"]["warranty_id"], row["id"])
        self.assertEqual(notice["payload"]["expires_on"], "2026-12-01")
        self.assertEqual(self.client.delete(f"{URL}{row['id']}/").status_code, 204)
        self.assertFalse(Notification.objects.exists())

    @override_settings(WARRANTY_PROOF_RETENTION_DAYS=7, WARRANTY_RECORD_RETENTION_DAYS=0)
    def test_retention_removes_old_proof_and_supports_optional_record_purge(self):
        old = self.add(duration_months=1)
        current = self.add(duration_months=12)
        self.assertEqual(self.proof(old["id"]).status_code, 204)
        self.assertEqual(self.proof(current["id"]).status_code, 204)
        self.assertEqual(purge_warranty_data(today=date(2026, 11, 23)), 1)
        self.assertEqual(Warranty.objects.count(), 2)
        self.assertEqual(WarrantyProof.objects.get().warranty_id, current["id"])
        with override_settings(WARRANTY_RECORD_RETENTION_DAYS=30):
            self.assertEqual(purge_warranty_data(today=date(2026, 11, 23)), 1)
        self.assertEqual(Warranty.objects.get().pk, current["id"])
