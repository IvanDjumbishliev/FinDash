from datetime import UTC, date, datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from api.models import Budget, CopilotPreferences, FinancialGoal, Portfolio, Subscription, Transaction, UserProfile
from api.views.deals import DEAL_CACHE_KEYS


class DashboardTests(TestCase):
    now = datetime(2026, 11, 21, 12, tzinfo=UTC)

    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="dashboard-test")
        self.other = get_user_model().objects.create_user(username="other-dashboard-test")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def record(self, amount, description, currency="EUR", owner=None, timestamp=None):
        Transaction.objects.create(
            user=owner or self.owner, timestamp=timestamp or self.now, currency=currency,
            particulars=description, amount=amount, category="groceries",
        )

    def test_dashboard_selects_sections_and_combines_monthly_calculations(self):
        UserProfile.objects.update_or_create(user=self.owner, defaults={"timezone": "Europe/Sofia"})
        self.record("150", "Pay")
        self.record("-35", "Market")
        self.record("5", "Merchant refund")
        self.record("-999", "Internal transfer")
        self.record("25", "Pay", "USD")
        self.record("-888", "Not this account", owner=self.other)
        self.record("-4", "Late on October UTC", timestamp=datetime(2026, 10, 31, 22, 30, tzinfo=UTC))
        with patch("api.views.dashboard.timezone.now", return_value=self.now), CaptureQueriesContext(connection) as queries:
            response = self.client.get("/api/dashboard/", {"sections": "monthly,overview"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(set(response.data), {"month", "username", "activity", "recent"})
        eur, usd = response.data["activity"]
        self.assertEqual((eur["income"], eur["expenses"], eur["net"]), ("150.00", "34.00", "116.00"))
        self.assertEqual(usd["currency"], "USD")
        self.assertEqual(len(response.data["recent"]), 5)
        self.assertNotIn("Not this account", str(response.data))
        self.assertLessEqual(len(queries), 3)

    def test_related_summaries_scope_to_the_user(self):
        for owner in (self.owner, self.other):
            Budget.objects.create(owner=owner, category="groceries", period=date(2026, 11, 1), amount=50, currency="EUR")
            FinancialGoal.objects.create(owner=owner, name="Travel", target_amount=300, currency="EUR")
            Portfolio.objects.create(owner=owner, name="Virtual")
            Subscription.objects.create(owner=owner, merchant=owner.username, estimated_amount=10, currency="EUR",
                                        normalized_merchant=owner.username, next_expected_payment=date(2026, 11, 30),
                                        billing_frequency="monthly", status="confirmed", detection_confidence=1)
            CopilotPreferences.objects.create(owner=owner, history_enabled=True,
                                              history=[{"response": {"answer": owner.username}}])
        with patch("api.views.dashboard.timezone.now", return_value=self.now):
            response = self.client.get("/api/dashboard/", {"sections": "budgets,goals,portfolio,subscriptions,insights"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["budgets"]), 1)
        self.assertEqual(response.data["goals"][0]["target"], "300.00")
        self.assertEqual(response.data["portfolio"]["count"], 1)
        self.assertEqual(response.data["subscriptions"][0]["merchant"], self.owner.username)
        self.assertEqual(response.data["insight"], self.owner.username)

    def test_dashboard_rejects_unknown_sections_and_requires_authentication(self):
        self.assertEqual(self.client.get("/api/dashboard/", {"sections": "invalid"}).status_code, 400)
        self.assertEqual(APIClient().get("/api/dashboard/").status_code, 401)

    def test_deals_can_use_cached_offers_without_network_requests(self):
        key = DEAL_CACHE_KEYS["lidl"]
        cache.set(key, [{"name": "Milk", "price": "2.00 €"}], timeout=60)
        self.addCleanup(cache.delete, key)
        with patch("api.views.deals.requests.get") as network:
            response = self.client.get("/api/dashboard/", {"sections": "deals"})
        network.assert_not_called()
        self.assertEqual(response.data["deals"][0]["display_price"], "2.00 €")
        self.assertNotIn("activity", response.data)

    def test_dashboard_forecast_uses_the_same_totals_without_the_detailed_series(self):
        compact = self.client.get("/api/forecast/cash-flow/", {"summary_only": "true"})
        full = self.client.get("/api/forecast/cash-flow/")
        self.assertEqual(compact.status_code, 200)
        self.assertEqual(set(compact.data), {"currency", "status", "totals"})
        self.assertEqual(compact.data["totals"], full.data["totals"])
