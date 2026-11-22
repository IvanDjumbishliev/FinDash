from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from api.models import GroceryOffer, Receipt, ReceiptItem, Transaction
from api.services.receipts import extract_receipt

BULGARIAN = """Магазин Тест
Фискален бон № 38491
21.11.2026 12:30:00
2 бр x 2,50 Кисело мляко 5,00 А
Отстъпка -0,50
Върнат хляб -1,25
Обща отстъпка 0,50
ДДС 0,54
Общо 3,25 лв.
В брой 5,00
Ресто 1,75
"""


class ReceiptExtractionTests(SimpleTestCase):
    def test_bulgarian_amounts_quantity_discounts_and_refund(self):
        result = extract_receipt(BULGARIAN, "DMY")
        self.assertEqual(result["currency"], "BGN")
        self.assertEqual(result["purchased_at"], "2026-11-21T12:30:00+02:00")
        self.assertEqual(result["reference"], "38491")
        self.assertEqual(result["total"], "3.25")
        self.assertEqual(result["tax_total"], "0.54")
        self.assertEqual(result["discounts"], "0.50")
        milk, bread = result["items"]
        self.assertEqual(milk["category"], "yogurt")
        self.assertEqual(milk["quantity"], "2.000000")
        self.assertEqual(milk["discount"], "0.50")
        self.assertEqual(milk["line_total"], "4.50")
        self.assertEqual(bread["line_total"], "-1.25")

    def test_english_weighted_item_and_explicit_date_order(self):
        result = extract_receipt("Sample Market\n11/21/2026 13:00\n500 g x 0.02 Rice 10.00\nTOTAL € 10.00", "MDY")
        self.assertEqual(result["currency"], "EUR")
        self.assertEqual(result["total"], "10.00")
        self.assertEqual(result["items"][0]["unit"], "kg")
        self.assertEqual(Decimal(result["items"][0]["quantity"]), Decimal("0.5"))
        self.assertEqual(Decimal(result["items"][0]["unit_price"]), Decimal("20.00"))
        self.assertIsNone(extract_receipt("Milk 1.00\nTotal 1.00", "DMY")["currency"])


class ReceiptApiTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user(username="receipt-owner")
        self.other = users.create_user(username="receipt-other")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def upload(self, color="white", source="camera"):
        content = BytesIO()
        Image.new("RGB", (30, 50), color).save(content, "PNG")
        return self.client.post("/api/receipts/preview/", {
            "file": SimpleUploadedFile("receipt.png", content.getvalue(), "image/png"), "source": source,
        }, format="multipart")

    @patch("api.views.receipts.recognize_receipt", return_value=BULGARIAN)
    def test_preview_and_atomic_idempotent_confirmation(self, ocr):
        preview = self.upload()
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertEqual(preview["Cache-Control"], "no-store")
        self.assertEqual(preview.data["status"], "review_required")
        self.assertFalse(Receipt.objects.exists())
        self.assertFalse(ReceiptItem.objects.exists())
        body = {**preview.data["receipt"], "token": preview.data["token"]}
        confirmed = self.client.post("/api/receipts/confirm/", body, format="json")
        self.assertEqual(confirmed.status_code, 201, confirmed.data)
        self.assertEqual(confirmed.data["items"][1]["line_total"], "-1.25")
        self.assertEqual(confirmed.data["source"], "camera")
        self.assertFalse(Transaction.objects.exists())
        repeated = self.client.post("/api/receipts/confirm/", {**body, "total": "5.00"}, format="json")
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.data["id"], confirmed.data["id"])
        exact = self.upload()
        self.assertEqual(exact.data["status"], "duplicate")
        distinct_photo = self.upload("black")
        repeated = self.client.post("/api/receipts/confirm/", {
            **distinct_photo.data["receipt"], "token": distinct_photo.data["token"],
        }, format="json")
        self.assertEqual(repeated.data["id"], confirmed.data["id"])
        self.assertEqual(ocr.call_count, 2)
        self.assertEqual(ReceiptItem.objects.count(), 2)

    @patch("api.views.receipts.recognize_receipt", return_value=BULGARIAN)
    def test_permissions_bad_input_and_expired_token(self, ocr):
        preview = self.upload()
        body = {**preview.data["receipt"], "token": preview.data["token"]}
        self.assertEqual(self.client.post("/api/receipts/confirm/", {**body, "currency": "USD"}, format="json").status_code, 400)
        self.assertEqual(self.client.post("/api/receipts/confirm/", {
            **body, "items": [{**body["items"][0], "confidence": "1.01"}],
        }, format="json").status_code, 400)
        with patch("api.views.receipts.PREVIEW_MAX_AGE", -1):
            self.assertEqual(self.client.post("/api/receipts/confirm/", body, format="json").status_code, 400)
        receipt = self.client.post("/api/receipts/confirm/", body, format="json")
        url = f'/api/receipts/{receipt.data["id"]}/'
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post("/api/receipts/confirm/", body, format="json").status_code, 400)
        self.assertEqual(self.client.get("/api/receipts/").data["count"], 0)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.delete(url).status_code, 404)
        self.assertEqual(self.client.patch(url + "reconciliation/", {"transaction": None}, format="json").status_code, 404)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/receipts/").status_code, 401)

    @patch("api.views.receipts.recognize_receipt", return_value=BULGARIAN)
    def test_catalog_link_and_explicit_reconciliation_leave_ledger_untouched(self, ocr):
        offer = GroceryOffer.objects.create(retailer="lidl", fingerprint="milk", product_name="Кисело мляко",
                                           brand="Example", last_successful_update=timezone.now())
        preview = self.upload()
        body = {**preview.data["receipt"], "token": preview.data["token"]}
        body["items"][0]["product"] = offer.pk
        receipt = self.client.post("/api/receipts/confirm/", body, format="json")
        self.assertEqual(receipt.status_code, 201, receipt.data)
        self.assertEqual(receipt.data["items"][0]["product"], offer.pk)
        self.assertEqual(receipt.data["items"][0]["brand"], "Example")
        url = f'/api/receipts/{receipt.data["id"]}/reconciliation/'
        for owner, amount, currency, expected in (
            (self.other, "-3.25", "BGN", 404), (self.owner, "3.25", "BGN", 400),
            (self.owner, "-3.25", "EUR", 400), (self.owner, "-3.25", "BGN", 200),
        ):
            payment = Transaction.objects.create(user=owner, amount=amount, currency=currency,
                                                 timestamp=timezone.now(), category="groceries")
            result = self.client.patch(url, {"transaction": payment.pk}, format="json")
            self.assertEqual(result.status_code, expected, result.data)
        self.assertTrue(result.data["reconciliation_valid"])
        second_preview = self.upload("black")
        second = self.client.post("/api/receipts/confirm/", {
            **second_preview.data["receipt"], "token": second_preview.data["token"], "reference": "different",
        }, format="json")
        conflict = self.client.patch(f'/api/receipts/{second.data["id"]}/reconciliation/',
                                     {"transaction": payment.pk}, format="json")
        self.assertEqual(conflict.status_code, 409)
        payment.refresh_from_db()
        self.assertEqual(payment.amount, Decimal("-3.25"))
        self.assertEqual(Transaction.objects.count(), 4)
        detached = self.client.patch(url, {"transaction": None}, format="json")
        self.assertFalse(detached.data["reconciliation_valid"])

    @patch("api.views.receipts.recognize_receipt", return_value=BULGARIAN)
    def test_failed_item_insert_rolls_back_and_confirmation_can_be_retried(self, ocr):
        preview = self.upload()
        body = {**preview.data["receipt"], "token": preview.data["token"]}
        with patch.object(ReceiptItem.objects, "bulk_create", side_effect=IntegrityError):
            with self.assertRaises(IntegrityError):
                self.client.post("/api/receipts/confirm/", body, format="json")
        self.assertFalse(Receipt.objects.exists())
        self.assertFalse(ReceiptItem.objects.exists())
        response = self.client.post("/api/receipts/confirm/", body, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(ReceiptItem.objects.count(), 2)

    @patch("api.views.receipts.recognize_receipt")
    def test_rejects_spoofed_images_and_bounds_uploads(self, ocr):
        def send(content):
            return self.client.post("/api/receipts/preview/", {
                "file": SimpleUploadedFile("receipt.png", content, "image/png"),
            }, format="multipart")

        self.assertEqual(send(b"%PDF-1.0").status_code, 415)
        with patch("api.views.receipts.MAX_BYTES", 100):
            self.assertEqual(send(b"a" * 120).status_code, 413)
        ocr.assert_not_called()
