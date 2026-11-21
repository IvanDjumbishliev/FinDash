from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone as django_timezone
from rest_framework.test import APIClient

from api.models import Budget, Transaction


class BudgetTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user(username="budget-owner")
        self.other = users.objects.create_user(username="other-budget-owner")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def create(self, **overrides):
        return self.client.post("/api/budgets/", {
            **{"period": "2026-02", "category": "groceries", "amount": "100.00", "currency": "EUR"},
            **overrides,
        }, format="json")

    def record(self, amount, moment="2026-02-12T12:00:00+00:00", **overrides):
        return Transaction.objects.create(
            amount=Decimal(amount),
            timestamp=datetime.fromisoformat(moment),
            **{
                **{"user": self.owner, "particulars": "Purchase", "category": "groceries", "currency": "EUR"},
                **overrides,
            },
        )

    def test_category_and_overall_net_spending_without_currency_conversion(self):
        self.record("-60.00", currency="eur")
        self.record("10.00", particulars="Merchant refund")
        self.record("500.00", particulars="Salary")
        self.record("-100.00", particulars="Transfer to savings")
        self.record("100.00", particulars="Internal transfer refund")
        self.record("-20.00", category="bills", particulars="Transfer to utility provider")
        self.record("-50.00", currency="USD")
        self.record("20.00", currency="USD", particulars="Refund")
        self.record("-90.00", user=self.other)

        groceries = self.create(currency="eur", alert_thresholds=[100, 50, 80])
        self.assertEqual(groceries.status_code, 201, groceries.data)
        self.assertEqual(groceries.data["currency"], "EUR")
        self.assertEqual(groceries.data["alert_thresholds"], [50, 80, 100])
        self.assertEqual(groceries.data["actual_spending"], "50.00")
        self.assertEqual(groceries.data["remaining"], "50.00")
        self.assertEqual(groceries.data["percentage_used"], "50.00")
        self.assertEqual(groceries.data["reached_thresholds"], [50])

        overall = self.create(category=None, amount="60.00")
        self.assertEqual(overall.status_code, 201, overall.data)
        self.assertEqual(overall.data["actual_spending"], "70.00")
        self.assertEqual(overall.data["remaining"], "-10.00")
        self.assertEqual(overall.data["percentage_used"], "116.67")
        self.assertEqual(overall.data["reached_thresholds"], [50, 80, 100])
        self.assertEqual(self.create(category="bills", currency="USD").data["actual_spending"], "0.00")

    def test_calendar_month_half_open_boundaries_and_leap_day(self):
        with django_timezone.override(timezone(timedelta(hours=2))):
            self.record("-40", "2024-01-31T21:59:59+00:00")
            self.record("-10", "2024-01-31T22:00:00+00:00")
            self.record("-15", "2024-02-29T21:59:59+00:00")
            self.record("-80", "2024-02-29T22:00:00+00:00")
            response = self.create(period="2024-02-01")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["period"], "2024-02-01")
        self.assertEqual(response.data["actual_spending"], "25.00")

    def test_refund_only_period_and_exact_alert_thresholds(self):
        self.record("20.00", particulars="Възстановена сума")
        budget = self.create(amount="1000.00", alert_thresholds=[50])
        self.assertEqual(budget.data["actual_spending"], "0.00")
        self.record("-519.99")
        url = f"/api/budgets/{budget.data['id']}/"
        calculated = self.client.get(url).data
        self.assertEqual(calculated["percentage_used"], "50.00")
        self.assertEqual(calculated["reached_thresholds"], [])
        self.record("-0.01")
        self.assertEqual(self.client.get(url).data["reached_thresholds"], [50])

    def test_duplicates_are_blocked_and_archiving_allows_a_replacement(self):
        first = self.create()
        self.assertEqual(first.status_code, 201)
        self.assertEqual(self.create(currency="USD").status_code, 400)
        self.assertEqual(self.create(category=None).status_code, 201)
        self.assertEqual(self.create(category=None, currency="BGN").status_code, 400)
        self.assertEqual(self.create(period="2026-03").status_code, 201)

        url = f"/api/budgets/{first.data['id']}/"
        archived = self.client.patch(url, {"archived": True, "amount": "75.00"}, format="json")
        self.assertEqual(archived.status_code, 200)
        self.assertEqual(archived.data["amount"], "75.00")
        self.assertTrue(archived.data["archived"])
        replacement = self.create(currency="USD")
        self.assertEqual(replacement.status_code, 201)
        self.assertEqual(self.client.patch(url, {"archived": False}, format="json").status_code, 400)
        self.assertEqual(self.client.delete(f"/api/budgets/{replacement.data['id']}/").status_code, 204)
        self.assertEqual(self.client.patch(url, {"archived": False}, format="json").status_code, 200)

    def test_database_enforces_uniqueness_and_month_start(self):
        data = {
            "owner": self.owner, "period": datetime(2026, 2, 1).date(),
            "category": None, "amount": Decimal("100"), "currency": "EUR",
        }
        Budget.objects.create(**data)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Budget.objects.create(**data)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Budget.objects.create(**{**data, "period": datetime(2026, 2, 2).date()})

    def test_invalid_fields_are_rejected_and_empty_thresholds_are_supported(self):
        for fields in (
            {"amount": "0"}, {"currency": "EU"}, {"currency": "15A"},
            {"period": "2026-02-03"}, {"period": "2026-13"}, {"period": "9999-12"},
            {"category": "invalid"}, {"alert_thresholds": [0, 50]}, {"alert_thresholds": [50, 50]},
        ):
            with self.subTest(fields=fields):
                self.assertEqual(self.create(**fields).status_code, 400)
        self.assertEqual(self.create(alert_thresholds=[]).data["alert_thresholds"], [])
        self.assertEqual(self.client.get("/api/budgets/overview/?period=2026-02-02").status_code, 400)

    def test_overview_uses_active_budgets_and_history_groups_all_saved_months(self):
        overall = self.create(category=None)
        current = self.create()
        archived = self.create(category="bills", archived=True)
        past = self.create(period="2026-01")
        with patch("api.views.budgets.timezone.localdate", return_value=datetime(2026, 2, 22).date()):
            overview = self.client.get("/api/budgets/overview/").data
        self.assertEqual(overview["period"], "2026-02-01")
        self.assertEqual(overview["overall"]["id"], overall.data["id"])
        self.assertEqual([item["id"] for item in overview["budgets"]], [current.data["id"]])
        self.assertIsNone(self.client.get("/api/budgets/overview/?period=2026-01").data["overall"])
        self.assertEqual(len(self.client.get("/api/budgets/?period=2026-02").data), 3)
        periods = self.client.get("/api/budgets/history/").data["periods"]
        self.assertEqual([item["period"] for item in periods], ["2026-02-01", "2026-01-01"])
        self.assertIn(archived.data["id"], [item["id"] for item in periods[0]["budgets"]])
        self.assertEqual(periods[1]["budgets"][0]["id"], past.data["id"])

    def test_owner_isolation_for_all_endpoints_and_authentication_required(self):
        saved = self.create(owner=self.other.pk)
        self.assertEqual(saved.status_code, 201, saved.data)
        self.assertTrue(Budget.objects.filter(pk=saved.data["id"], owner=self.owner).exists())
        detail = f"/api/budgets/{saved.data['id']}/"
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get("/api/budgets/").data, [])
        self.assertEqual(self.client.get("/api/budgets/history/").data, {"periods": []})
        self.assertEqual(self.client.get("/api/budgets/overview/?period=2026-02").data["budgets"], [])
        self.assertEqual(self.client.get(detail).status_code, 404)
        self.assertEqual(self.client.patch(detail, {"archived": True}, format="json").status_code, 404)
        self.assertEqual(self.client.delete(detail).status_code, 404)
        self.assertEqual(self.create().status_code, 201)
        self.client.force_authenticate(None)
        for method, url in [
            ("get", "/api/budgets/"), ("post", "/api/budgets/"), ("get", detail),
            ("get", "/api/budgets/overview/"), ("get", "/api/budgets/history/"),
            ("patch", detail), ("delete", detail),
        ]:
            self.assertEqual(getattr(self.client, method)(url).status_code, 401)
