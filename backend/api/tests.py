from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from api.models import Transaction


class DealEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        cache.clear()

    @override_settings(API_KEY=None)
    def test_store_endpoints_return_empty_deals_when_not_configured(self):
        for store in ("lidl", "kaufland"):
            with self.subTest(store=store):
                response = self.client.get(f"/api/leaflet/{store}/")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["response"], [])
                self.assertIn("not configured", response.data["notice"].lower())

    def test_billa_endpoint_reports_unavailable_without_error(self):
        response = self.client.get("/api/leaflet/billa/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["response"], [])
        self.assertFalse(response.data["available"])
        self.assertIn("not yet available", response.data["notice"].lower())

    @override_settings(API_KEY=None)
    def test_search_returns_helpful_response_when_not_configured(self):
        response = self.client.post(
            "/api/leaflet/user/", {"prompt": "milk"}, format="json"
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["response"], [])
        self.assertIn("not configured", response.data["error"].lower())

    @override_settings(API_KEY="test-key")
    def test_search_returns_empty_list_when_ai_has_no_matches(self):
        cache.set("last_fetch_timestamp_kaufland", "today")
        cache.set("today_kaufland", ["kaufland leaflet"])
        cache.set("last_fetch_timestamp_lidl", "today")
        cache.set("today_lidl", ["lidl leaflet"])
        fake_client = SimpleNamespace(
            models=SimpleNamespace(
                generate_content=lambda **kwargs: SimpleNamespace(text="[]")
            )
        )
        with patch("api.views.leaflet_user.client", fake_client):
            response = self.client.post(
                "/api/leaflet/user/", {"prompt": "milk"}, format="json"
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["response"], [])

    @override_settings(API_KEY="test-key")
    def test_search_returns_helpful_response_when_leaflets_are_missing(self):
        response = self.client.post(
            "/api/leaflet/user/", {"prompt": "milk"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["response"], [])
        self.assertIn("not available", response.data["error"].lower())


class AIEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="ai-test-user", password="test")
        self.client.force_authenticate(user=self.user)
        cache.clear()

    @override_settings(API_KEY="")
    def test_chat_returns_503_when_api_key_is_empty(self):
        response = self.client.post(
            "/api/chat/", {"prompt": "Summarize my spending"}, format="json"
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.data,
            {"error": "AI features are not configured. Add API_KEY to backend/.env"},
        )

    @override_settings(API_KEY=None)
    def test_summary_returns_503_when_api_key_is_missing_even_without_transactions(self):
        response = self.client.get("/api/summary/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.data,
            {"error": "AI features are not configured. Add API_KEY to backend/.env"},
        )

    @override_settings(API_KEY="test-key")
    def test_lazy_client_uses_supported_google_genai_sdk(self):
        from api.views.client import LazyGenAIClient

        fake_sdk_client = SimpleNamespace(models=object())
        with patch(
            "api.views.client.genai.Client", return_value=fake_sdk_client
        ) as client_factory:
            lazy_client = LazyGenAIClient()
            self.assertIs(lazy_client.models, fake_sdk_client.models)

        client_factory.assert_called_once_with(api_key="test-key")

    @override_settings(API_KEY="test-key")
    def test_chat_uses_google_genai_generate_content(self):
        fake_client = SimpleNamespace(
            models=SimpleNamespace(
                generate_content=Mock(
                    return_value=SimpleNamespace(text="Helpful answer")
                )
            )
        )
        with patch("api.views.assistant.client", fake_client):
            response = self.client.post(
                "/api/chat/", {"prompt": "How can I save?"}, format="json"
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data, "Helpful answer")
        fake_client.models.generate_content.assert_called_once()
        call = fake_client.models.generate_content.call_args.kwargs
        self.assertEqual(call["model"], "gemini-2.0-flash")
        self.assertIsInstance(call["contents"], list)

    @override_settings(API_KEY="test-key")
    def test_summary_uses_google_genai_generate_content(self):
        Transaction.objects.create(
            user=self.user,
            amount="12.50",
            category=Transaction.Category.GROCERIES,
            particulars="Groceries",
            currency="USD",
        )
        fake_client = SimpleNamespace(
            models=SimpleNamespace(
                generate_content=Mock(
                    return_value=SimpleNamespace(
                        text='[{"title":"Spending","description":"Track groceries."}]'
                    )
                )
            )
        )
        with patch("api.views.user_summary.client", fake_client):
            response = self.client.get("/api/summary/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]["title"], "Spending")
        fake_client.models.generate_content.assert_called_once()
        call = fake_client.models.generate_content.call_args.kwargs
        self.assertEqual(call["model"], "gemini-2.0-flash")
        self.assertIn(
            "response_schema",
            call["config"],
        )
