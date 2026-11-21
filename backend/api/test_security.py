import logging
import re
from datetime import datetime, timezone
from uuid import UUID

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from api.models import Transaction
from api.services.notifications import after_commit
from api.urls import urlpatterns
from api.views.deals import allowed_brochure_origin
from backend.privacy import RedactRequestLog, ThrottleRedisSerializer


class SecurityTests(TestCase):
    def test_every_private_api_route_rejects_unauthenticated_access(self):
        client = APIClient()
        public_groups = {"deals/", "leaflet/", "news/"}
        for entry in urlpatterns:
            route = str(entry.pattern)
            if any(route.startswith(prefix) for prefix in public_groups):
                continue
            path = re.sub(r"<int:\w+>", "1", route)
            path = re.sub(r"<uuid:\w+>", str(UUID(int=0)), path)
            view = entry.callback.cls
            method = next(method for method in ("get", "post", "patch", "delete")
                          if method in view.http_method_names and hasattr(view, method))
            with self.subTest(method=method, path=path):
                response = getattr(client, method)("/api/" + path)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_registration_validates_password_and_ip_throttle(self):
        client = APIClient()
        for attempt in range(6):
            response = client.post("/api/user/register/", {
                "username": f"security-{attempt}", "password": "password",
            }, format="json")
            self.assertEqual(response.status_code, 400)
            self.assertIn("password", response.data)
        response = client.post("/api/user/register/", {"username": "limit"}, format="json",
                               HTTP_X_FORWARDED_FOR="192.0.2.1")
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)
        self.assertFalse(User.objects.exists())

    def test_access_expires_in_ten_minutes_refresh_rotates_and_logout_revokes(self):
        client = APIClient()
        user = User.objects.create_user(username="security-auth", password="Synthetic-strong-pass-45")
        login = client.post("/api/token/", {"username": user.username, "password": "Synthetic-strong-pass-45"}, format="json")
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.headers["Cache-Control"], "no-store")
        access = AccessToken(login.data["access"])
        self.assertEqual(access["exp"] - access["iat"], 600)
        original = login.data["refresh"]
        result = client.post("/api/token/refresh/", {"refresh": original}, format="json")
        self.assertEqual(result.status_code, 200)
        rotated = result.data["refresh"]
        self.assertNotEqual(original, rotated)
        self.assertEqual(client.post("/api/token/refresh/", {"refresh": original}, format="json").status_code, 401)
        self.assertEqual(client.post("/api/token/logout/", {"refresh": rotated}, format="json").status_code, 200)
        self.assertEqual(client.post("/api/token/refresh/", {"refresh": rotated}, format="json").status_code, 401)

    def test_transactions_cannot_be_read_or_deleted_by_a_different_account(self):
        owner = User.objects.create_user(username="private-ledger")
        other = User.objects.create_user(username="other-ledger")
        row = Transaction.objects.create(user=owner, amount="-20", currency="EUR", particulars="Synthetic",
                                         timestamp=datetime.now(timezone.utc))
        client = APIClient()
        client.force_authenticate(other)
        self.assertEqual(client.get("/api/transactions/").data, [])
        self.assertEqual(client.delete(f"/api/transaction/{row.pk}/").status_code, 404)
        self.assertTrue(Transaction.objects.filter(pk=row.pk, user=owner).exists())

    def test_statement_does_not_accept_multiple_files_or_oversized_mapping(self):
        client = APIClient()
        client.force_authenticate(User.objects.create_user(username="upload-security"))
        path = "/api/bank-statement/preview/"
        file = lambda: SimpleUploadedFile("example.csv", b"date,description,amount\n2026-01-01,Milk,2", content_type="text/csv")
        response = client.post(path, {"file": [file(), file()]}, format="multipart")
        self.assertEqual(response.status_code, 400)
        response = client.post(path, {"file": file(), "mapping": "[" * 5000}, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertIn("too large", response.data["error"])

    def test_brochure_origin_validation_and_log_filter(self):
        self.assertTrue(allowed_brochure_origin("https://assets.flippingbook.com/example", "flippingbook.com"))
        for url in ("http://assets.flippingbook.com/", "https://example.test/", "https://assets.flippingbook.com.example.test/",
                    "https://private@assets.flippingbook.com/", "https://assets.flippingbook.com:8443/"):
            self.assertFalse(allowed_brochure_origin(url, "flippingbook.com"))
        entry = logging.LogRecord("django.request", logging.ERROR, "", 0, "Request to %s",
                                  ("/api/?balance=123",), None)
        entry.status_code = 500
        entry.exc_text = "Synthetic private request content"
        self.assertTrue(RedactRequestLog().filter(entry))
        self.assertEqual(entry.getMessage(), "HTTP request failed (status 500)")
        self.assertIsNone(entry.exc_text)

    def test_shared_rate_cache_accepts_only_json_histories(self):
        serializer = ThrottleRedisSerializer()
        self.assertEqual(serializer.loads(serializer.dumps([1.25, 2.50])), [1.25, 2.50])
        self.assertEqual(serializer.loads(b"malformed cache value"), [])
        self.assertEqual(serializer.loads(b'{"history": []}'), [])

    def test_post_commit_error_is_redacted(self):
        def fail():
            raise RuntimeError("Synthetic private record")

        with self.assertLogs("api.services.notifications", level="WARNING") as logs:
            with self.captureOnCommitCallbacks(execute=True):
                after_commit(fail)
        self.assertEqual(logs.output, [
            "WARNING:api.services.notifications:Post-commit notification processing failed",
        ])
