import re

from django.test import SimpleTestCase

from api.urls import urlpatterns


class OpenApiTests(SimpleTestCase):
    def setUp(self):
        response = self.client.get("/api/schema/?format=json")
        self.assertEqual(response.status_code, 200)
        self.schema = response.json()

    def test_openapi_documents_every_api_route(self):
        documented = {
            re.sub(r"\{[^}]+\}", "{}", path) for path in self.schema["paths"]
        }
        expected = {
            "/api/" + re.sub(r"<[^>]+>", "{}", str(entry.pattern)) for entry in urlpatterns
        }
        self.assertFalse(expected - documented, expected - documented)
        self.assertNotIn("/api/schema/", self.schema["paths"])
        self.assertTrue(self.schema["openapi"].startswith("3."))

    def test_token_auth_payload_multipart_and_pdf_contracts(self):
        paths = self.schema["paths"]
        self.assertIn({"jwtAuth": []}, paths["/api/transactions/"]["post"]["security"])
        self.assertFalse(paths["/api/token/"]["post"].get("security"))
        self.assertIn("201", paths["/api/user/register/"]["post"]["responses"])
        multipart = paths["/api/bank-statement/preview/"]["post"]["requestBody"]["content"]["multipart/form-data"]
        name = multipart["schema"]["$ref"].rsplit("/", 1)[-1]
        fields = self.schema["components"]["schemas"][name]["properties"]
        self.assertEqual(fields["file"]["format"], "binary")
        pdf = paths["/api/reports/pdf/"]["post"]["responses"]["200"]["content"]
        self.assertEqual(pdf["application/pdf"]["schema"]["format"], "binary")
        optimizer = paths["/api/grocery/optimize/"]["post"]
        self.assertIn("application/json", optimizer["requestBody"]["content"])

    def test_development_swagger_uses_schema_without_persisting_credentials(self):
        ui = self.client.get("/api/docs/")
        self.assertEqual(ui.status_code, 200)
        self.assertContains(ui, "/api/schema/")
        self.assertContains(ui, '"persistAuthorization": false')
