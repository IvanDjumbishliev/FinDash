from datetime import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from api.models import Transaction, UserProfile


class SpendingHeatmapTests(TestCase):
    url = "/api/analytics/spending-heatmap/"
    timezone_url = "/api/user/profile/timezone/"

    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user(username="heatmap-owner")
        self.other = users.objects.create_user(username="heatmap-other")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def record(self, moment, amount="-10.00", **overrides):
        return Transaction.objects.create(
            **{
                "user": self.owner,
                "timestamp": datetime.fromisoformat(moment),
                "amount": amount,
                "category": "groceries",
                "currency": "USD",
                "particulars": "Market purchase",
                **overrides,
            },
        )

    def test_local_midnight_boundaries_across_daylight_saving(self):
        response = self.client.patch(self.timezone_url, {"timezone": "Europe/Sofia"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.record("2026-03-28T21:59:59+00:00")
        self.record("2026-03-28T22:00:00+00:00", "-5.00")
        self.record("2026-03-29T20:59:59+00:00", "-7.00")
        self.record("2026-03-29T21:00:00+00:00", "-2.00")
        self.record("2026-03-30T21:00:00+00:00")

        response = self.client.get(self.url, {"start": "2026-03-29", "end": "2026-03-30"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["timezone"], "Europe/Sofia")
        self.assertEqual(response.data["days"], [
            {"date": "2026-03-29", "total_spending": "12.00", "transaction_count": 2,
             "category_totals": {"groceries": "12.00"}, "category_counts": {"groceries": 2}},
            {"date": "2026-03-30", "total_spending": "2.00", "transaction_count": 1,
             "category_totals": {"groceries": "2.00"}, "category_counts": {"groceries": 1}},
        ])

    def test_clock_rollback_can_reenter_the_last_requested_date(self):
        UserProfile.objects.create(user=self.owner, timezone="America/Goose_Bay")
        self.record("2009-11-01T02:59:00+00:00", "-1.00")
        self.record("2009-11-01T03:00:00+00:00", "-2.00")
        self.record("2009-11-01T03:30:00+00:00", "-4.00")

        response = self.client.get(self.url, {"start": "2009-10-31", "end": "2009-10-31"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["days"], [
            {"date": "2009-10-31", "total_spending": "5.00", "transaction_count": 2,
             "category_totals": {"groceries": "5.00"}, "category_counts": {"groceries": 2}},
        ])

    def test_empty_days_currency_isolation_and_constant_query_count(self):
        UserProfile.objects.create(user=self.owner, currency="EUR")
        moment = "2026-01-02T12:00:00+00:00"
        self.record(moment, currency="eur")
        self.record(moment)
        self.record(moment, amount="-100.00", currency="EUR", user=self.other)
        self.owner.refresh_from_db()

        with self.assertNumQueries(2):
            response = self.client.get(self.url, {"start": "2026-01-01", "end": "2026-01-03"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["currency"], "EUR")
        self.assertEqual(response.data["days"], [
            {"date": "2026-01-01", "total_spending": "0.00", "transaction_count": 0, "category_totals": {}, "category_counts": {}},
            {"date": "2026-01-02", "total_spending": "10.00", "transaction_count": 1,
             "category_totals": {"groceries": "10.00"}, "category_counts": {"groceries": 1}},
            {"date": "2026-01-03", "total_spending": "0.00", "transaction_count": 0, "category_totals": {}, "category_counts": {}},
        ])
        overridden = self.client.get(self.url, {"start": "2026-01-02", "end": "2026-01-02", "currency": "usd"})
        self.assertEqual(overridden.data["currency"], "USD")
        self.assertEqual(overridden.data["days"][0]["transaction_count"], 1)

    def test_refunds_reduce_net_spending_and_transfers_and_income_are_excluded(self):
        moment = "2026-01-02T12:00:00+00:00"
        self.record(moment)
        self.record(moment, "2.00", particulars="Merchant refund")
        self.record(moment, "-4.00", category="bills")
        self.record(moment, "30.00", particulars="Salary")
        self.record(moment, "-40.00", particulars="Transfer to savings")
        self.record(moment, "40.00", particulars="Internal transfer refund")
        self.record("2026-01-03T12:00:00+00:00", "5.00", particulars="Card reversal")

        response = self.client.get(self.url, {"start": "2026-01-02", "end": "2026-01-03"})
        self.assertEqual(response.data["days"], [
            {"date": "2026-01-02", "total_spending": "12.00", "transaction_count": 3,
             "category_totals": {"bills": "4.00", "groceries": "8.00"},
             "category_counts": {"bills": 1, "groceries": 2}},
            {"date": "2026-01-03", "total_spending": "-5.00", "transaction_count": 1,
             "category_totals": {"groceries": "-5.00"}, "category_counts": {"groceries": 1}},
        ])

    def test_default_history_ends_on_local_today(self):
        UserProfile.objects.create(user=self.owner, timezone="Europe/Sofia")
        with patch("django.utils.timezone.now", return_value=datetime.fromisoformat("2026-01-01T23:00:00+00:00")):
            response = self.client.get(self.url)
        self.assertEqual(response.data["end"], "2026-01-02")
        self.assertEqual(len(response.data["days"]), 366)

    def test_invalid_ranges_and_currency_are_rejected(self):
        for query in (
            {"start": "2026-02-30"},
            {"start": "2026-02-02", "end": "2026-02-01"},
            {"start": "2025-01-01", "end": "2026-01-02"},
            {"end": "9999-12-31"},
            {"currency": "EURO"},
        ):
            with self.subTest(query=query):
                self.assertEqual(self.client.get(self.url, query).status_code, 400)

    def test_timezone_preference_validation_and_ownership(self):
        self.assertEqual(self.client.get(self.timezone_url).data, {"timezone": "UTC"})
        invalid = self.client.patch(self.timezone_url, {"timezone": "Not/AZone"}, format="json")
        self.assertEqual(invalid.status_code, 400)
        self.client.patch(self.timezone_url, {"timezone": "Europe/Sofia", "user": self.other.pk}, format="json")
        self.assertEqual(self.client.get(self.timezone_url).data, {"timezone": "Europe/Sofia"})
        self.assertFalse(UserProfile.objects.filter(user=self.other).exists())

    def test_endpoints_require_authentication(self):
        client = APIClient()
        self.assertEqual(client.get(self.url).status_code, 401)
        self.assertEqual(client.get(self.timezone_url).status_code, 401)
        self.assertEqual(client.patch(self.timezone_url, {"timezone": "UTC"}).status_code, 401)

    def test_day_detail_uses_same_spending_rules_and_owner_scope(self):
        UserProfile.objects.create(user=self.owner, timezone="Europe/Sofia")
        moment = "2026-03-28T22:30:00+00:00"
        purchase = self.record(moment, merchant="Market")
        refund = self.record(moment, "3.00", particulars="Card reversal")
        self.record(moment, category="bills")
        self.record(moment, user=self.other)
        self.record(moment, currency="EUR")
        self.record(moment, particulars="Transfer to savings")
        self.record("2026-03-28T21:59:59+00:00")

        url = self.url + "day/"
        response = self.client.get(url, {"date": "2026-03-29", "category": "groceries"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["transactions"], [
            {"id": refund.pk, "timestamp": "2026-03-29T00:30:00+02:00", "category": "groceries",
             "description": "Card reversal", "spending": "-3.00"},
            {"id": purchase.pk, "timestamp": "2026-03-29T00:30:00+02:00", "category": "groceries",
             "description": "Market", "spending": "10.00"},
        ])
        self.assertEqual(self.client.get(url, {"date": "2026-03-30"}).data["transactions"], [])
        self.assertEqual(self.client.get(url, {"date": "bad"}).status_code, 400)
        self.assertEqual(APIClient().get(url, {"date": "2026-03-29"}).status_code, 401)
