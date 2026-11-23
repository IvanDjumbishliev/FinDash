from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image, PngImagePlugin
from rest_framework.test import APIClient

from api.models import LoyaltyCardImage

URL = "/api/loyalty-cards/"


class LoyaltyWalletTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user(username="wallet-owner")
        self.other = users.create_user(username="wallet-stranger")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def add(self, **changes):
        return self.client.post(URL, {"retailer": "Fixture Store", "identifier": "MEM-001234", **changes}, format="json")

    def upload(self, pk, *, confirm="true", content=None):
        if content is None:
            result = BytesIO()
            info = PngImagePlugin.PngInfo()
            info.add_text("Comment", "Remove this metadata")
            Image.new("RGB", (80, 42), "white").save(result, "PNG", pnginfo=info)
            content = result.getvalue()
        return self.client.post(f"{URL}{pk}/image/", {
            "file": SimpleUploadedFile("loyalty.png", content, content_type="image/png"), "loyalty_only": confirm,
        }, format="multipart")

    def test_private_identifiers_are_only_in_owned_authenticated_detail(self):
        response = self.add()
        self.assertEqual(response.status_code, 201, response.data)
        pk = response.data["id"]
        self.assertNotIn("identifier", response.data)
        self.assertNotIn("identifier", self.client.get(URL).data[0])
        detail = self.client.get(f"{URL}{pk}/")
        self.assertEqual(detail.data["identifier"], "MEM-001234")
        self.assertEqual(detail["Cache-Control"], "no-store")
        self.assertEqual(self.upload(pk).status_code, 204)

        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(URL).data, [])
        for method, path in (
            ("get", f"{URL}{pk}/"), ("patch", f"{URL}{pk}/"), ("delete", f"{URL}{pk}/"),
            ("get", f"{URL}{pk}/image/"), ("delete", f"{URL}{pk}/image/"),
        ):
            self.assertEqual(getattr(self.client, method)(path).status_code, 404)
        self.assertEqual(self.upload(pk).status_code, 404)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(URL).status_code, 401)
        self.assertEqual(self.client.get(f"{URL}{pk}/image/").status_code, 401)

    def test_requires_original_format_confirmation_and_gtin_check_digit(self):
        self.assertEqual(self.add(code_format="qrcode").status_code, 400)
        self.assertEqual(self.add(code_format="qrcode", original_format_confirmed="true").status_code, 400)
        response = self.add(code_format="upca", identifier="036000291452", original_format_confirmed=True)
        self.assertEqual(response.status_code, 201, response.data)
        detail = f"{URL}{response.data['id']}/"
        self.assertEqual(self.client.get(detail).data["identifier"], "036000291452")
        self.assertEqual(self.client.patch(detail, {"favorite": True}, format="json").status_code, 200)
        self.assertEqual(self.client.patch(detail, {"code_format": "qrcode"}, format="json").status_code, 400)
        self.assertEqual(self.add(code_format="upca", identifier="036000291453", original_format_confirmed=True).status_code, 400)
        self.assertEqual(self.add(code_format="unknown", original_format_confirmed=True).status_code, 400)
        self.assertEqual(self.client.patch(detail, {"code_format": "none"}, format="json").status_code, 200)
        self.assertEqual(self.client.get(detail).data["identifier"], "036000291452")

    def test_rejects_payment_numbers_credential_fields_and_non_literal_identifiers(self):
        for fields in (
            {"identifier": "4111 1111 1111 1111"}, {"identifier": "4111-1111-1111-1111"},
            {"identifier": "https://example.com/secret"}, {"identifier": 1234},
            {"password": "example"}, {"token": "example"},
        ):
            with self.subTest(fields=fields):
                self.assertEqual(self.add(**fields).status_code, 400)
        self.assertEqual(self.client.get(URL).data, [])

    def test_validates_images_strips_metadata_and_deletes_attachment_with_card(self):
        pk = self.add().data["id"]
        self.assertEqual(self.upload(pk, confirm="false").status_code, 400)
        self.assertEqual(self.upload(pk, content=b"<script>invalid</script>").status_code, 415)
        from unittest.mock import patch
        with patch("api.views.receipts.MAX_BYTES", 64):
            self.assertEqual(self.upload(pk, content=b"x" * 100).status_code, 413)
        self.assertEqual(self.upload(pk).status_code, 204)
        image = self.client.get(f"{URL}{pk}/image/")
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image["Cache-Control"], "no-store")
        self.assertEqual(image["X-Content-Type-Options"], "nosniff")
        self.assertNotIn(b"Remove this metadata", image.content)
        self.assertEqual(self.client.delete(f"{URL}{pk}/image/").status_code, 204)
        self.assertEqual(self.client.get(f"{URL}{pk}/image/").status_code, 404)
        self.assertEqual(self.upload(pk).status_code, 204)
        self.assertEqual(self.client.delete(f"{URL}{pk}/").status_code, 204)
        self.assertFalse(LoyaltyCardImage.objects.exists())
