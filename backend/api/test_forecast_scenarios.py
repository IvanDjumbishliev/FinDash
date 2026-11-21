from datetime import UTC, date, datetime, time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from api.models import Budget, CashFlowScenario, Subscription, Transaction


class CashFlowScenarioTests(TestCase):
    as_of = date(2026, 5, 15)
    url = "/api/forecast/cash-flow/scenarios/"

    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user(username="scenario-owner")
        self.other = users.objects.create_user(username="scenario-other")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.guest = APIClient()
        self.other_client = APIClient()
        self.other_client.force_authenticate(self.other)

    def subscription(self, owner):
        return Subscription.objects.create(
            owner=owner, merchant="Streaming", normalized_merchant="streaming",
            status="confirmed", currency="USD", billing_frequency="monthly",
            next_expected_payment=date(2026, 5, 20), estimated_amount="20",
            detection_confidence="0.80",
        )

    def seed(self):
        for offset in range(1, 13):
            day = self.as_of - timedelta(weeks=offset)
            for category, amount in (("groceries", "-70"), ("transport", "-35")):
                Transaction.objects.create(
                    user=self.owner, amount=amount, category=category, currency="USD",
                    timestamp=datetime.combine(day, time(12), UTC), particulars=f"{category} {offset}",
                )
        Budget.objects.create(owner=self.owner, category="groceries", currency="USD", period=date(2026, 5, 1), amount=400)
        return self.subscription(self.owner)

    def snapshot(self):
        return {model.__name__: list(model.objects.order_by("pk").values()) for model in (Transaction, Subscription, Budget)}

    def preview(self, changes, client=None, **params):
        with patch("api.services.forecasting.timezone.localdate", return_value=self.as_of):
            return (client or self.client).post(self.url + "preview/", {"changes": changes, **params}, format="json")

    def test_combines_all_adjustments_and_never_writes_financial_records(self):
        subscription = self.seed()
        before = self.snapshot()
        changes = {
            "monthly_income": {"amount": "200.00"},
            "spending_reduction": {"category": "groceries", "percent": 50},
            "recurring_expense": {"amount": "10.00", "day": 2, "frequency": "weekly"},
            "remove_subscription_id": subscription.pk,
            "purchase": {"amount": "35.00", "day": 5},
            "starting_balance": "1100.00",
        }
        with CaptureQueriesContext(connection) as queries:
            response = self.preview(changes, starting_balance="1000.00", horizon=30)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertTrue(response.data["hypothetical"])
        self.assertEqual(response.data["days"][0]["balance_difference"], "100.00")
        self.assertEqual(response.data["totals"], {
            "date": "2026-06-14", "baseline_net_cash_flow": "-470.00", "scenario_net_cash_flow": "-185.00",
            "baseline_balance": "530.00", "scenario_balance": "915.00", "balance_difference": "385.00",
            "net_cash_flow_difference": "285.00",
        })
        self.assertTrue(all(query["sql"].lstrip().upper().startswith("SELECT") for query in queries))
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(CashFlowScenario.objects.exists())

        repeat = self.preview(changes, starting_balance="1000.00", horizon=30)
        self.assertEqual(repeat.data, response.data)
        self.assertEqual(self.snapshot(), before)

    def test_sparse_history_and_outside_horizon_changes_are_explicit(self):
        foreign = self.subscription(self.other)
        response = self.preview({
            "spending_reduction": {"category": "groceries", "percent": 50},
            "purchase": {"amount": "30", "day": 31},
            "remove_subscription_id": foreign.pk,
            "starting_balance": "-300",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "insufficient_history")
        self.assertEqual(response.data["totals"]["scenario_balance"], "-300.00")
        self.assertIsNone(response.data["totals"]["balance_difference"])
        self.assertEqual(len(response.data["notes"]), 3)
        self.assertEqual(response.data, self.preview({
            "spending_reduction": {"category": "groceries", "percent": 50},
            "purchase": {"amount": "30", "day": 31},
            "remove_subscription_id": foreign.pk + 1000,
            "starting_balance": "-300",
        }).data)

    def test_saved_scenarios_are_account_scoped_and_financial_records_are_unchanged(self):
        self.seed()
        before = self.snapshot()
        body = {"name": "Less spending", "currency": "usd", "horizon": 60, "changes": {"purchase": {"amount": "15.25"}}}
        self.assertEqual(self.guest.post(self.url, body, format="json").status_code, 401)
        self.assertEqual(self.guest.get(self.url).status_code, 401)
        self.assertEqual(self.preview({"starting_balance": "0"}, client=self.guest).status_code, 401)
        created = self.client.post(self.url, {**body, "owner": self.other.pk}, format="json")
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data["changes"], {"purchase": {"amount": "15.25", "day": 1}})
        self.assertEqual(created.data["currency"], "USD")
        self.assertEqual(self.client.post(self.url, body, format="json").status_code, 400)
        self.assertEqual(len(self.client.get(self.url).data), 1)
        self.assertEqual(self.other_client.get(self.url).data, [])
        target = f"{self.url}{created.data['id']}/"
        self.assertEqual(self.other_client.delete(target).status_code, 404)
        self.assertEqual(self.client.delete(target).status_code, 204)
        self.assertEqual(self.client.get(self.url).data, [])
        self.assertEqual(self.snapshot(), before)

    def test_validation_rejects_invalid_changes_before_running_forecast(self):
        for changes in (
            {}, {"purchase": {"amount": "-1"}}, {"purchase": {"amount": "1", "day": 91}},
            {"recurring_expense": {"amount": "1", "frequency": "every day"}},
            {"spending_reduction": {"category": "unavailable", "percent": 100}},
            {"spending_reduction": {"category": "groceries", "percent": 101}},
            {"remove_subscription_id": -1}, {"starting_balance": "1.005"},
        ):
            with self.subTest(changes=changes), patch("api.views.forecast_scenarios.build_cash_flow_forecast") as forecast:
                self.assertEqual(self.preview(changes).status_code, 400)
                forecast.assert_not_called()
