from unittest.mock import patch

from django.db import OperationalError, connections
from django.test import Client, SimpleTestCase, override_settings


class DeploymentChecks(SimpleTestCase):
    def test_health_reports_readiness_without_database_details(self):
        with patch.object(connections["default"], "cursor") as cursor:
            response = self.client.get("/healthz/")
        cursor.return_value.__enter__.return_value.execute.assert_called_once_with("SELECT 1")
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertIn("no-store", response.headers["Cache-Control"])

        with patch.object(connections["default"], "cursor", side_effect=OperationalError("Private database configuration")):
            response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})
        self.assertEqual(self.client.post("/healthz/").status_code, 405)

    @override_settings(CORS_ALLOWED_ORIGINS=["https://frontend.example"])
    def test_cors_only_grants_listed_origins_access_to_api(self):
        def preflight(path, origin):
            return self.client.options(
                path, headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization, x-starting-balance",
                },
            )

        result = preflight("/api/token/", "https://frontend.example")
        self.assertEqual(result.headers["Access-Control-Allow-Origin"], "https://frontend.example")
        self.assertIn("x-starting-balance", result.headers["Access-Control-Allow-Headers"])
        self.assertNotIn("Access-Control-Allow-Credentials", result.headers)
        self.assertNotIn("Access-Control-Allow-Origin", preflight("/api/token/", "https://other.example").headers)
        self.assertNotIn("Access-Control-Allow-Origin", preflight("/admin/", "https://frontend.example").headers)

    @override_settings(ALLOWED_HOSTS=["app.example"], DEBUG=False, SECURE_SSL_REDIRECT=True,
                       SECURE_REDIRECT_EXEMPT=[r"^healthz/$"])
    def test_host_validation_https_redirect_and_internal_health(self):
        self.assertEqual(self.client.get("/api/token/", headers={"Host": "other.example"}).status_code, 400)
        redirect = self.client.get("/admin/", headers={"Host": "app.example"})
        self.assertEqual(redirect.headers["Location"], "https://app.example/admin/")
        with patch.object(connections["default"], "cursor"):
            self.assertEqual(self.client.get("/healthz/", headers={"Host": "app.example"}).status_code, 200)

    @override_settings(ALLOWED_HOSTS=["app.example"], CSRF_COOKIE_SECURE=True, CSRF_COOKIE_HTTPONLY=True)
    def test_secure_admin_cookie_and_untrusted_csrf_origin(self):
        client = Client(enforce_csrf_checks=True)
        login = client.get("/admin/login/", secure=True, headers={"Host": "app.example"})
        cookie = login.cookies["csrftoken"]
        self.assertTrue(cookie["secure"])
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")

        response = client.post("/admin/login/", {"csrfmiddlewaretoken": cookie.value}, secure=True,
                               headers={"Host": "app.example", "Origin": "https://other.example"})
        self.assertEqual(response.status_code, 403)
        response = client.post("/admin/login/", {"csrfmiddlewaretoken": cookie.value}, secure=True,
                               headers={"Host": "app.example", "Origin": "https://app.example"})
        self.assertEqual(response.status_code, 200)
