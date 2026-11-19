from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient


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
