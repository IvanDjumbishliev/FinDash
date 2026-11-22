from decimal import Decimal
from io import BytesIO
from unittest.mock import Mock, patch

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
        self.assertEqual(milk["quantity"], "2")
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

    @patch("api.services.receipts.recognize_receipt", return_value=BULGARIAN)
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

    @patch("api.services.receipts.recognize_receipt", return_value=BULGARIAN)
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

    @patch("api.services.receipts.recognize_receipt", return_value=BULGARIAN)
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

    @patch("api.services.receipts.recognize_receipt", return_value=BULGARIAN)
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

    @patch("api.services.receipts.recognize_receipt")
    def test_rejects_spoofed_images_and_bounds_uploads(self, ocr):
        def send(content):
            return self.client.post("/api/receipts/preview/", {
                "file": SimpleUploadedFile("receipt.png", content, "image/png"),
            }, format="multipart")

        self.assertEqual(send(b"%PDF-1.0").status_code, 415)
        with patch("api.views.receipts.MAX_BYTES", 100):
            self.assertEqual(send(b"a" * 120).status_code, 413)
        ocr.assert_not_called()


class ReceiptImagePipelineTests(SimpleTestCase):
    def test_corrects_exif_orientation_and_removes_metadata(self):
        from api.services.receipts import receipt_image

        image = Image.new("RGB", (48, 24), "white")
        exif = image.getexif()
        exif[274] = 6
        buffer = BytesIO()
        image.save(buffer, "JPEG", exif=exif)
        _, processed = receipt_image(SimpleUploadedFile("rotated.jpg", buffer.getvalue(), "image/jpeg"))
        with Image.open(BytesIO(processed)) as cleaned:
            self.assertEqual(cleaned.size, (24, 48))
            self.assertEqual(cleaned.mode, "L")
            self.assertFalse(cleaned.getexif())

    def test_decodes_real_heic_and_webp(self):
        from pillow_heif import register_heif_opener

        from api.services.receipts import receipt_image

        register_heif_opener()
        for extension, codec in [("heic", "HEIF"), ("webp", "WEBP")]:
            with self.subTest(extension=extension):
                buffer = BytesIO()
                Image.new("RGB", (64, 32), "white").save(buffer, codec)
                _, processed = receipt_image(SimpleUploadedFile(
                    f"photo.{extension}", buffer.getvalue(), f"image/{extension}",
                ))
                with Image.open(BytesIO(processed)) as cleaned:
                    self.assertEqual(cleaned.size, (64, 32))

    def test_missing_time_and_mismatched_totals_stay_explicit(self):
        receipt = extract_receipt("Магазин\n23.11.2026\nКис. мл. 2,50\nОбщо 4,50 EUR", "DMY")
        self.assertEqual(receipt["purchase_date"], "2026-11-23")
        self.assertIsNone(receipt["purchased_at"])
        self.assertIsNone(receipt["tax_total"])
        self.assertEqual(receipt["items"][0]["original_description"], "Кис. мл.")
        self.assertEqual(receipt["items"][0]["normalized_name"], "кисело мляко")
        self.assertEqual(receipt["totals_check"], {"status": "mismatch", "item_total": "2.50", "difference": "2.00"})
        self.assertTrue(receipt["warnings"])


class ReceiptPreviewPipelineTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="receipt-pipeline-user")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def images(self, *colors):
        files = []
        for color in colors:
            content = BytesIO()
            Image.new("RGB", (32, 64), color).save(content, "PNG")
            files.append(SimpleUploadedFile("receipt.png", content.getvalue(), "image/png"))
        return files

    @patch("api.services.receipts.recognize_receipt")
    def test_multi_image_preview_merges_overlapping_ocr_lines(self, ocr):
        ocr.side_effect = [
            "Sample Market\n23.11.2026 10:00\nMilk 2.00\nBread 1.00",
            "Milk 2.00\nBread 1.00\nRice 3.00\nTOTAL 6.00 EUR",
        ]
        response = self.client.post("/api/receipts/preview/", {
            "file": self.images("black", "white"), "source": "gallery",
        }, format="multipart")
        self.assertEqual(response.status_code, 200, response.data)
        preview = response.data["receipt"]
        self.assertEqual([item["original_description"] for item in preview["items"]], ["Milk", "Bread", "Rice"])
        self.assertEqual(preview["totals_check"]["status"], "matches")
        self.assertIn("page boundary", preview["warnings"][0])
        self.assertFalse(Receipt.objects.exists())

    @patch("api.services.receipts.recognize_receipt", return_value="")
    def test_unreadable_receipt_and_image_count(self, ocr):
        too_many = self.client.post("/api/receipts/preview/", {
            "file": self.images("white", "black", "gray", "red"),
        }, format="multipart")
        self.assertEqual(too_many.status_code, 400)
        ocr.assert_not_called()
        unreadable = self.client.post("/api/receipts/preview/", {"file": self.images("white")}, format="multipart")
        self.assertEqual(unreadable.status_code, 422)
        self.assertIn("Retake", unreadable.data["detail"])

    @patch("api.services.receipts.recognize_receipt",
           return_value="Sample Market\n23.11.2026 10:00\nRice\n3.00\nTOTAL 3.00 EUR")
    @patch("api.services.receipt_ai.client", new_callable=Mock)
    def test_gemini_requires_explicit_consent_and_grounded_lines(self, gemini, ocr):
        from django.test import override_settings

        with override_settings(API_KEY="test-key"):
            blank = self.client.post("/api/receipts/preview/", {"file": self.images("white")}, format="multipart")
            self.assertEqual(blank.data["ai_status"], "not_requested")
            self.assertFalse(blank.data["receipt"]["items"])
            bad_consent = self.client.post("/api/receipts/preview/", {
                "file": self.images("white"), "allow_ai": "on",
            }, format="multipart")
            self.assertEqual(bad_consent.status_code, 400)
            gemini.models.generate_content.assert_not_called()

            gemini.models.generate_content.return_value = Mock(
                text='{"merchant_line":0,"items":[{"description_line":2,"amount_line":3},'
                     '{"description_line":90,"amount_line":91}]}',
            )
            consented = self.client.post("/api/receipts/preview/", {
                "file": self.images("white"), "allow_ai": "true",
            }, format="multipart")
            self.assertEqual(consented.data["ai_status"], "used")
            self.assertEqual(consented.data["receipt"]["items"][0]["line_total"], "3.00")
            self.assertEqual(len(consented.data["receipt"]["items"]), 1)
            sent = gemini.models.generate_content.call_args.kwargs
            self.assertTrue(all(isinstance(part, str) for part in sent["contents"]))
            self.assertIn("response_json_schema", sent["config"])

            gemini.models.generate_content.return_value = Mock(
                text='{"merchant_line":0,"items":[{"description_line":2,"amount_line":3,"price":"100.00"}]}',
            )
            rejected = self.client.post("/api/receipts/preview/", {
                "file": self.images("white"), "allow_ai": "true",
            }, format="multipart")
            self.assertEqual(rejected.data["ai_status"], "unavailable")
            self.assertEqual(rejected.data["receipt"]["items"], [])

    @patch("api.services.receipts.recognize_receipt", return_value=BULGARIAN)
    def test_possible_duplicate_different_photo_is_scoped_and_keeps_review_open(self, ocr):
        first = self.client.post("/api/receipts/preview/", {"file": self.images("white")}, format="multipart")
        receipt = self.client.post("/api/receipts/confirm/", {
            **first.data["receipt"], "token": first.data["token"],
        }, format="json")
        second = self.client.post("/api/receipts/preview/", {"file": self.images("black")}, format="multipart")
        self.assertEqual(second.data["status"], "review_required")
        self.assertEqual([str(pk) for pk in second.data["possible_duplicate_ids"]], [receipt.data["id"]])
        other = get_user_model().objects.create_user(username="receipt-pipeline-other")
        self.client.force_authenticate(other)
        theirs = self.client.post("/api/receipts/preview/", {"file": self.images("white")}, format="multipart")
        self.assertEqual(theirs.data["possible_duplicate_ids"], [])
        self.assertIsNone(theirs.data["duplicate_id"])
