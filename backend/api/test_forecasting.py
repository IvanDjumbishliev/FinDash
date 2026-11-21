from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from api.models import Budget, Subscription, Transaction, UserProfile
from api.services.forecasting import build_cash_flow_forecast


class ForecastTests(TestCase):
    as_of = date(2026, 5, 15)
    url = "/api/forecast/cash-flow/"

    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user(username="forecast-owner")
        self.other = users.objects.create_user(username="forecast-other")
        self.client = APIClient()

    def record(self, day, amount, label="Purchase", **fields):
        if isinstance(day, date) and not isinstance(day, datetime):
            day = datetime.combine(day, time(12), UTC)
        return Transaction.objects.create(**{
            "user": self.owner, "timestamp": day, "amount": amount, "particulars": label,
            "category": "general", "currency": "USD", **fields,
        })

    def subscription(self, name, **fields):
        return Subscription.objects.create(**{
            "owner": self.owner, "merchant": name, "normalized_merchant": name.lower(),
            "currency": "USD", "status": Subscription.Status.CONFIRMED,
            "estimated_amount": "20.00", "billing_frequency": Subscription.Frequency.MONTHLY,
            "billing_anchor_day": 20, "next_expected_payment": date(2026, 5, 20),
            "detection_confidence": "0.90", **fields,
        })

    def forecast(self, **kwargs):
        return build_cash_flow_forecast(self.owner, as_of=self.as_of, **kwargs)

    def test_recurring_income_and_calendar_anchored_expenses(self):
        for offset in (49, 35, 21, 7):
            day = self.as_of - timedelta(days=offset)
            self.record(day, "900", f"Payroll {day.isoformat()}")
        for day in (date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)):
            self.record(day, "-40", "Card payment: Utilities ref 412301")
        for day in (date(2025, 8, 31), date(2025, 11, 30), date(2026, 2, 28)):
            self.record(day, "-45", "Quarterly dues")
        for year in (2023, 2024, 2025):
            self.record(date(year, 6, 30), "-60", "Annual permit")
        for day in (date(2026, 1, 10), date(2026, 2, 10), date(2026, 3, 10)):
            self.record(day, "-50", "Stale contract")
        self.record(date(2026, 5, 12), "10000", "Merchant refund")
        self.record(date(2026, 5, 13), "-10000", "Transfer to savings")
        self.record(date(2026, 5, 14), "10000", "Internal transfer")

        result = self.forecast(horizon=90)
        by_name = {item["label"]: item for item in result["recurring"]}
        self.assertEqual(by_name["Payroll"]["kind"], "income")
        self.assertEqual(by_name["Payroll"]["frequency"], "biweekly")
        self.assertEqual(by_name["Payroll"]["dates"][:2], ["2026-05-22", "2026-06-05"])
        self.assertEqual(by_name["Utilities"]["dates"], ["2026-05-31", "2026-06-30", "2026-07-31"])
        self.assertEqual(by_name["Quarterly dues"]["dates"], ["2026-05-31"])
        self.assertEqual(by_name["Annual permit"]["dates"], ["2026-06-30"])
        self.assertNotIn("Stale contract", by_name)
        self.assertEqual(result["history"]["recorded_income"], "3600.00")
        self.assertEqual(result["history"]["recorded_refunds"], "10000.00")
        self.assertEqual(result["history"]["recorded_gross_expenses"], "625.00")
        self.assertEqual(len(result["days"]), 90)
        self.assertEqual(result["start_date"], "2026-05-16")
        self.assertEqual(result["end_date"], "2026-08-13")

    def test_confirmed_charges_are_not_counted_twice_and_inactive_charges_stay_out(self):
        self.subscription("Internet")
        self.subscription("Paused radio", tracking_status=Subscription.TrackingStatus.PAUSED)
        self.subscription("Canceled tv", tracking_status=Subscription.TrackingStatus.CANCELED)
        self.subscription("Unverified", status=Subscription.Status.CANDIDATE)
        self.subscription("Other currency", currency="EUR")
        self.subscription("Other account", owner=self.other)
        # Include a rate change and an unrelated expense with the same merchant profile.
        for month, charge in ((12, "-10"), (1, "-10"), (2, "-10"), (3, "-20"), (4, "-20")):
            day = date(2025 if month == 12 else 2026, month, 20)
            self.record(day, charge, "CARD PAYMENT: Internet")
            self.record(day, "-20", "Paused radio")
            self.record(day, "-20", "Canceled tv")
        for week in range(1, 23):
            self.record(self.as_of - timedelta(weeks=week), "-7", f"One-off expense {week}")
        self.record(date(2026, 4, 9), "-7", "Additional charge", merchant="Internet")
        Budget.objects.create(owner=self.owner, period=date(2026, 5, 1), currency="USD", amount=500)

        result = self.forecast(horizon=30, starting_balance=Decimal("1000.00"))
        self.assertEqual(len(result["recurring"]), 1)
        charge = result["recurring"][0]
        self.assertEqual(charge["source"], "confirmed_subscription")
        self.assertEqual(charge["dates"], ["2026-05-20"])
        self.assertEqual(result["totals"]["scheduled_expenses"], "20.00")
        self.assertEqual(result["totals"]["scheduled_only_ending_balance"], "980.00")
        self.assertEqual(result["totals"]["estimated_variable_expenses"], "30.00")
        self.assertEqual(result["totals"]["estimated_ending_balance"], "950.00")
        self.assertEqual(Subscription.objects.count(), 6)

    def test_variable_estimates_cap_extreme_weeks_and_have_reproducible_scenarios(self):
        for week in range(1, 21):
            day = self.as_of - timedelta(weeks=week)
            self.record(day, -Decimal(18 + week % 4), f"Expense {week}")
            if week % 3 == 0 or week == 2:
                self.record(day, Decimal(45 + (week % 5) * 5), f"Contract {week}")
        outlier = self.record(self.as_of - timedelta(weeks=2), "-10000", "Unexpected large expense")
        balance = Decimal("-75.50")
        result = self.forecast(horizon=60, starting_balance=balance)
        self.assertEqual(result["status"], "estimated")
        self.assertEqual(result["history"]["baseline"]["complete_weeks"], 20)
        self.assertEqual(result["recurring"], [])
        totals = result["totals"]
        self.assertGreater(Decimal(totals["estimated_variable_income"]), 0)
        self.assertLess(Decimal(totals["estimated_variable_expenses"]), 210)
        self.assertEqual(
            sum(Decimal(day["estimated_net_cash_flow"]) for day in result["days"]),
            Decimal(totals["estimated_net_cash_flow"]),
        )
        self.assertEqual(result["days"][-1]["estimated_balance"], totals["estimated_ending_balance"])
        scenarios = result["uncertainty"]
        self.assertEqual(scenarios["label"], "Historical scenario range")
        self.assertLess(Decimal(scenarios["net_cash_flow"]["lower"]), Decimal(scenarios["net_cash_flow"]["upper"]))
        self.assertEqual(Decimal(scenarios["ending_balance"]["lower"]), balance + Decimal(scenarios["net_cash_flow"]["lower"]))

        outlier.amount = "-100000"
        outlier.save(update_fields=["amount"])
        after = self.forecast(horizon=60, starting_balance=balance)
        self.assertEqual(after["uncertainty"], scenarios)
        self.assertEqual(after["totals"], totals)
        flow_only = self.forecast(horizon=60)
        self.assertIsNone(flow_only["uncertainty"]["ending_balance"])
        self.assertIsNone(flow_only["totals"]["estimated_ending_balance"])
        self.assertTrue(all(day["estimated_balance"] is None for day in flow_only["days"]))

    def test_sparse_history_has_no_variable_or_full_balance_projection(self):
        self.subscription("Streaming")
        self.record(self.as_of - timedelta(weeks=24), "30", "Rare income")
        self.record(self.as_of - timedelta(days=2), "-10", "Recent purchase")
        result = self.forecast(starting_balance=Decimal("200"))
        self.assertEqual(result["status"], "insufficient_history")
        self.assertEqual(result["history"]["baseline"]["weeks_with_recorded_activity"], 2)
        self.assertEqual(result["totals"]["scheduled_only_ending_balance"], "180.00")
        self.assertIsNone(result["totals"]["estimated_ending_balance"])
        self.assertIsNone(result["totals"]["estimated_variable_income"])
        self.assertIsNone(result["uncertainty"])

    def test_constant_variable_history_has_no_scenario_range(self):
        for week in range(1, 19):
            self.record(self.as_of - timedelta(weeks=week), "-70", f"Weekly activity {week}")
        result = self.forecast(horizon=30)
        self.assertEqual(result["status"], "estimated")
        self.assertEqual(result["totals"]["estimated_variable_expenses"], "300.00")
        self.assertIsNone(result["uncertainty"])

    def test_owner_currency_timezone_and_balance_header(self):
        UserProfile.objects.create(user=self.owner, timezone="Europe/Sofia", currency="EUR")
        self.record(datetime(2026, 5, 14, 21, tzinfo=UTC), "50", "Income", currency="eur")
        self.record(datetime(2026, 5, 15, 21, tzinfo=UTC), "5000", "Tomorrow", currency="EUR")
        self.record(self.as_of, "5000", "Other currency")
        self.record(self.as_of, "9000", "Other account", user=self.other, currency="EUR")
        self.subscription("Other account", owner=self.other, currency="EUR")

        self.assertEqual(self.client.get(self.url).status_code, 401)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.owner)}")
        with patch("api.services.forecasting.timezone.now", return_value=datetime(2026, 5, 14, 22, tzinfo=UTC)):
            response = self.client.get(self.url, {"horizon": "60", "owner": self.other.pk}, HTTP_X_STARTING_BALANCE="-12.10")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.data["currency"], "EUR")
        self.assertEqual(response.data["timezone"], "Europe/Sofia")
        self.assertEqual(response.data["as_of"], "2026-05-15")
        self.assertEqual(response.data["history"]["last_activity"], "2026-05-15")
        self.assertEqual(response.data["history"]["recorded_income"], "50.00")
        self.assertEqual(response.data["starting_balance"], "-12.10")
        self.assertEqual(len(response.data["days"]), 60)
        self.assertEqual(response.data["recurring"], [])

    def test_request_validation_and_processing_limit(self):
        self.client.force_authenticate(self.owner)
        for query in (
            {"horizon": 45}, {"currency": "US12"}, {"starting_balance": "0.001"},
            {"starting_balance": "NaN"}, {"starting_balance": "100000000000000.00"},
        ):
            with self.subTest(query=query):
                self.assertEqual(self.client.get(self.url, query).status_code, 400)
        self.assertEqual(self.client.get(self.url, {"starting_balance": "7"}, HTTP_X_STARTING_BALANCE="8").status_code, 400)
        self.assertEqual(self.client.get(self.url, {"starting_balance": "12.12"}).data["starting_balance"], "12.12")
        self.record(self.as_of, "-10")
        with patch("api.services.forecasting.MAX_LEDGER_ROWS", 0), patch(
            "api.services.forecasting.timezone.localdate", return_value=self.as_of,
        ):
            self.assertEqual(self.client.get(self.url).status_code, 422)

    def test_weekly_pattern_requires_four_observations_and_rolls_forward(self):
        for offset in (34, 27, 20, 13, 6):
            self.record(self.as_of - timedelta(days=offset), "-12", "Weekly membership")
        for offset in (20, 13, 6):
            self.record(self.as_of - timedelta(days=offset), "-30", "Short sequence")
        self.subscription(
            "Older weekly subscription", billing_frequency=Subscription.Frequency.WEEKLY,
            next_expected_payment=date(2026, 4, 25), billing_anchor_day=None,
        )
        result = self.forecast(horizon=30)
        events = {event["label"]: event for event in result["recurring"]}
        self.assertEqual(set(events), {"Weekly membership", "Older weekly subscription"})
        for event in events.values():
            self.assertEqual(event["dates"][0], "2026-05-16")
            self.assertEqual(event["frequency"], "weekly")
        self.assertIsNone(result["days"][0]["estimated_balance"])

    def test_recurring_coverage_alone_cannot_support_a_variable_scenario_range(self):
        for week in range(1, 19):
            day = self.as_of - timedelta(weeks=week)
            self.record(day, "100", "Payroll")
            if week in (2, 7, 11):
                self.record(day, "20", f"Contract {week}")
        result = self.forecast()
        self.assertEqual(result["status"], "estimated")
        self.assertEqual(result["history"]["baseline"]["weeks_with_variable_activity"], 3)
        self.assertIsNone(result["uncertainty"])
