from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from api.models import FinancialGoal, GoalScenario, Transaction
from api.services.goal_scenarios import compare_goal_scenario


class GoalScenarioTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user(username="scenario-owner")
        self.other = users.objects.create_user(username="scenario-other")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.goal = FinancialGoal.objects.create(
            owner=self.owner, name="Savings", currency="EUR", target_amount=Decimal("1000.00"),
            monthly_contribution=Decimal("100.00"), target_date=date(2028, 8, 31),
        )
        self.today = date(2028, 1, 31)
        self.endpoint = f"/api/goals/{self.goal.pk}/scenarios/"

    def test_comparison_applies_one_time_and_expense_reduction_and_keeps_calendar_anchor(self):
        self.goal.current_amount = Decimal("100.00")
        result = compare_goal_scenario(self.goal, self.today, {
            "monthly_contribution": Decimal("150.00"), "expense_reduction": Decimal("25.00"),
            "one_time_contribution": Decimal("100.00"), "target_amount": Decimal("1025.00"),
            "target_date": date(2028, 6, 30),
        })
        baseline, scenario = result["baseline"], result["scenario"]
        self.assertEqual(baseline["projected_completion_date"], date(2028, 10, 31))
        self.assertFalse(baseline["projected_on_time"])
        self.assertEqual(scenario["projected_completion_date"], date(2028, 6, 30))
        self.assertTrue(scenario["projected_on_time"])
        self.assertEqual(scenario["monthly_contribution"], "175.00")
        self.assertEqual(result["months_saved"], 4)
        points = result["chart"]["points"]
        self.assertEqual(points[0], {"date": "2028-01-31", "baseline": "10.00", "scenario": "19.51"})
        self.assertEqual(points[1]["date"], "2028-02-29")
        self.assertEqual(points[2]["date"], "2028-03-31")
        self.assertEqual(points[-1]["scenario"], "100.00")

    def test_decreases_zero_rate_immediate_funding_and_large_horizons(self):
        slow = compare_goal_scenario(self.goal, self.today, {"monthly_contribution": Decimal("50")})
        self.assertEqual(slow["months_saved"], -10)
        zero = compare_goal_scenario(self.goal, self.today, {"monthly_contribution": Decimal("0"), "target_date": None})
        self.assertEqual(zero["scenario"]["status"], "no_contribution_rate")
        self.assertIsNone(zero["scenario"]["projected_completion_date"])
        self.assertIsNone(zero["scenario"]["target_date"])
        same_day = compare_goal_scenario(self.goal, self.today, {"one_time_contribution": Decimal("999.99"), "target_amount": Decimal("999.99")})
        self.assertEqual(same_day["scenario"]["projected_completion_date"], self.today)
        self.assertEqual(same_day["chart"]["points"][0]["scenario"], "100.00")
        far = compare_goal_scenario(self.goal, self.today, {"monthly_contribution": Decimal("0.01")})
        self.assertTrue(far["chart"]["truncated"])
        self.assertEqual(len(far["chart"]["points"]), 61)
        self.assertEqual(far["scenario"]["status"], "date_out_of_range")

    def test_preview_save_and_delete_leave_goal_ledger_and_transactions_untouched(self):
        goal_url = f"/api/goals/{self.goal.pk}/"
        write = self.client.post(goal_url + "contributions/", {"kind": "contribution", "amount": "120"}, format="json")
        self.assertEqual(write.status_code, 201)
        bank = Transaction.objects.create(
            user=self.owner, category="groceries", amount="-17.25", currency="EUR",
            timestamp=datetime(2028, 1, 1, tzinfo=UTC), particulars="Synthetic",
        )
        before = FinancialGoal.objects.values().get(pk=self.goal.pk)
        ledger = list(self.goal.contributions.values())
        payload = {"changes": {"one_time_contribution": "300.50", "expense_reduction": "20.00"}}
        with patch("django.utils.timezone.now", return_value=datetime(2028, 1, 31, 12, tzinfo=UTC)):
            result = self.client.post(self.endpoint + "preview/", payload, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result["Cache-Control"], "no-store")
        self.assertEqual(result.data["baseline"]["starting_amount"], "120.00")
        self.assertEqual(result.data["scenario"]["starting_amount"], "420.50")
        self.assertEqual(result.data["scenario"]["target_date"], self.goal.target_date)
        self.assertEqual(GoalScenario.objects.count(), 0)
        saved = self.client.post(self.endpoint, {"name": "Plan A", **payload}, format="json")
        self.assertEqual(saved.status_code, 201, saved.data)
        self.assertEqual(saved.data["changes"], payload["changes"])
        self.assertEqual(self.client.get(self.endpoint).data, [saved.data])
        self.assertEqual(self.client.delete(self.endpoint + f"{saved.data['id']}/").status_code, 204)
        self.assertEqual(FinancialGoal.objects.values().get(pk=self.goal.pk), before)
        self.assertEqual(list(self.goal.contributions.values()), ledger)
        bank.refresh_from_db()
        self.assertEqual(bank.amount, Decimal("-17.25"))
        self.assertEqual(Transaction.objects.count(), 1)

    def test_saved_scenario_reloads_against_current_goal_while_preserving_clear_date(self):
        saved = self.client.post(self.endpoint, {
            "name": "No deadline", "changes": {"monthly_contribution": "0", "target_date": None},
        }, format="json")
        self.assertEqual(saved.status_code, 201)
        self.assertEqual(saved.data["changes"], {"monthly_contribution": "0.00", "target_date": None})
        self.goal.current_amount = Decimal("12")
        self.goal.save(update_fields=["current_amount"])
        preview = self.client.post(self.endpoint + "preview/", {"changes": saved.data["changes"]}, format="json")
        self.assertEqual(preview.data["scenario"]["starting_amount"], "12.00")
        self.assertIsNone(preview.data["scenario"]["target_date"])

    def test_validates_input_and_isolates_scenarios_within_owner_and_goal(self):
        cases = [{"target_amount": "0"}, {"one_time_contribution": "-1"}, {"expense_reduction": "2.001"},
                 {"monthly_contribution": "NaN"}, {"target_date": "2028-02-30"}, {"current_amount": "100"}]
        for changes in cases:
            with self.subTest(changes=changes):
                self.assertEqual(self.client.post(self.endpoint + "preview/", {"changes": changes}, format="json").status_code, 400)
        empty = self.client.post(self.endpoint + "preview/", {"changes": {}}, format="json")
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.data["baseline"], empty.data["scenario"])
        self.assertEqual(self.client.post(self.endpoint, {"name": "Empty", "changes": {}}, format="json").status_code, 400)
        item = self.client.post(self.endpoint, {"name": "Plan", "changes": {"target_amount": "99"}}, format="json")
        self.assertEqual(item.status_code, 201)
        self.assertEqual(self.client.post(self.endpoint, {"name": "Plan", "changes": {"target_amount": "98"}}, format="json").status_code, 400)
        sibling = FinancialGoal.objects.create(owner=self.owner, name="Another", currency="EUR", target_amount=100)
        self.assertEqual(self.client.delete(f"/api/goals/{sibling.pk}/scenarios/{item.data['id']}/").status_code, 404)
        other_client = APIClient()
        self.assertEqual(other_client.get(self.endpoint).status_code, 401)
        other_client.force_authenticate(self.other)
        self.assertEqual(other_client.get(self.endpoint).status_code, 404)
        self.assertEqual(other_client.post(self.endpoint + "preview/", {"changes": {}}, format="json").status_code, 404)
        self.assertEqual(other_client.post(self.endpoint, {"changes": {}}, format="json").status_code, 404)
        self.assertEqual(other_client.delete(self.endpoint + f"{item.data['id']}/").status_code, 404)
