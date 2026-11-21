from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from api.models import FinancialGoal, GoalContribution, Transaction, UserProfile


class FinancialGoalTests(TestCase):
    url = "/api/goals/"

    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="goal-owner")
        self.other = get_user_model().objects.create_user(username="other-goal-owner")
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)
        self.other_client = APIClient()
        self.other_client.force_authenticate(user=self.other)

    def goal(self, **fields):
        response = self.client.post(self.url, {
            "name": "Emergency fund", "target_amount": "1000.00", "currency": "eur", **fields,
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response["Cache-Control"], "no-store")
        return f"{self.url}{response.data['id']}/"

    def entry(self, goal, amount, kind="contribution", **fields):
        return self.client.post(f"{goal}contributions/", {
            "kind": kind, "amount": amount, **fields,
        }, format="json")

    def test_multiple_goals_decimal_progress_and_immutable_ledger(self):
        bank_transaction = Transaction.objects.create(
            user=self.owner, amount="-25.10", currency="EUR", category="groceries",
            timestamp=datetime(2026, 10, 1, tzinfo=UTC), particulars="Synthetic statement entry",
        )
        goal = self.goal()
        second = self.goal(name="New laptop", currency="USD")
        self.assertEqual(len(self.client.get(self.url).data), 2)
        first = self.entry(goal, "350.20", note="First deposit").data
        self.assertEqual(first["entry"]["currency"], "EUR")
        self.assertEqual(first["goal"]["current_amount"], "350.20")
        self.assertEqual(first["goal"]["remaining_amount"], "649.80")
        self.assertEqual(first["goal"]["progress_percent"], "35.02")
        self.assertFalse(first["goal"]["completed"])
        withdrawal = self.entry(goal, "50.10", "withdrawal")
        self.assertEqual(withdrawal.status_code, 201)
        self.assertEqual(withdrawal.data["goal"]["current_amount"], "300.10")
        ledger = self.client.get(f"{goal}contributions/?limit=1").data
        self.assertEqual(ledger["count"], 2)
        self.assertIsNotNone(ledger["next"])
        self.assertEqual(ledger["results"][0]["balance_after"], "300.10")
        older = self.client.get(f"{goal}contributions/?offset=1").data["results"][0]
        self.assertEqual(older["balance_after"], "350.20")
        self.assertEqual(older["note"], "First deposit")
        self.assertEqual(self.client.get(second).data["current_amount"], "0.00")
        self.assertEqual(Transaction.objects.count(), 1)
        bank_transaction.refresh_from_db()
        self.assertEqual(bank_transaction.amount, Decimal("-25.10"))
        self.assertEqual(bank_transaction.particulars, "Synthetic statement entry")

    def test_archiving_preserves_completed_goal_and_withdrawal_can_reopen_it(self):
        goal = self.goal()
        paid = self.entry(goal, "1050.00").data["goal"]
        self.assertEqual(paid["remaining_amount"], "0.00")
        self.assertEqual(paid["progress_percent"], "105.00")
        self.assertTrue(paid["completed"])
        self.assertEqual(self.client.get(f"{goal}projection/").data["status"], "completed")
        self.assertTrue(self.client.patch(goal, {"archived": True}, format="json").data["archived"])
        self.assertEqual(self.entry(goal, "100", "withdrawal").status_code, 409)
        self.assertEqual(self.client.delete(goal).status_code, 409)
        self.assertEqual(self.client.get(f"{goal}contributions/").data["count"], 1)
        self.assertFalse(self.client.patch(goal, {"archived": False}, format="json").data["archived"])
        self.assertFalse(self.entry(goal, "100", "withdrawal").data["goal"]["completed"])
        self.assertEqual(self.client.delete(self.goal(name="Unused")).status_code, 204)

    def test_withdrawal_validation_and_currency_cannot_relabel_balance(self):
        goal = self.goal()
        self.assertEqual(self.entry(goal, "1", "withdrawal").status_code, 409)
        self.assertEqual(self.entry(goal, "-1").status_code, 400)
        self.assertEqual(self.entry(goal, "1.005").status_code, 400)
        self.assertEqual(self.entry(goal, "5", currency="USD").status_code, 400)
        self.assertEqual(self.client.patch(goal, {"currency": "XYZ"}, format="json").status_code, 400)
        self.assertEqual(self.entry(goal, "2", currency="eur").status_code, 201)
        self.assertEqual(self.entry(goal, "2.01", "withdrawal").status_code, 409)
        self.assertEqual(self.entry(goal, "2", "withdrawal").data["goal"]["current_amount"], "0.00")
        self.assertEqual(GoalContribution.objects.count(), 2)
        self.assertEqual(FinancialGoal.objects.get().current_amount, Decimal("0.00"))

    def test_calendar_projection_deadline_and_temporary_override(self):
        goal = self.goal(target_amount="300.01", target_date="2028-04-30", monthly_contribution="100")
        self.assertEqual(self.entry(goal, "0.01").status_code, 201)
        UserProfile.objects.update_or_create(user=self.owner, defaults={"timezone": "Europe/Sofia"})
        with patch("django.utils.timezone.now", return_value=datetime(2028, 1, 30, 22, 30, tzinfo=UTC)):
            base = self.client.get(f"{goal}projection/").data
            self.assertEqual(base["as_of"], "2028-01-31")
            self.assertEqual(base["projected_completion_date"], "2028-04-30")
            self.assertEqual(base["months_remaining"], 3)
            self.assertTrue(base["projected_on_time"])
            fast = self.client.get(f"{goal}projection/?monthly_contribution=300").data
            self.assertEqual(fast["projected_completion_date"], "2028-02-29")
            slow = self.client.get(f"{goal}projection/?monthly_contribution=99.99").data
            self.assertEqual(slow["projected_completion_date"], "2028-05-31")
            self.assertFalse(slow["projected_on_time"])
            self.assertEqual(self.client.get(f"{goal}projection/?monthly_contribution=0").data["status"],
                             "no_contribution_rate")
            self.assertEqual(self.client.get(f"{goal}projection/?monthly_contribution=-1").status_code, 400)
            self.assertEqual(self.client.get(goal).data["monthly_contribution"], "100.00")
        self.assertEqual(self.client.patch(goal, {"target_date": "2028-02-30"}, format="json").status_code, 400)
        self.assertIsNone(self.client.patch(goal, {"target_date": None}, format="json").data["target_date"])

    def test_projection_with_unconfigured_rate_or_unrepresentable_calendar_date(self):
        goal = self.goal(target_amount="999999999999.99")
        missing = self.client.get(f"{goal}projection/").data
        self.assertEqual(missing["status"], "no_contribution_rate")
        self.assertIsNone(missing["projected_completion_date"])
        distant = self.client.get(f"{goal}projection/?monthly_contribution=0.01").data
        self.assertEqual(distant["status"], "date_out_of_range")
        self.assertIsNone(distant["projected_completion_date"])

    def test_optional_request_id_replays_only_the_same_entry(self):
        goal = self.goal()
        request_id = str(uuid4())
        first = self.entry(goal, "25", request_id=request_id)
        replay = self.entry(goal, "25", request_id=request_id)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(first.data, replay.data)
        self.assertEqual(self.entry(goal, "26", request_id=request_id).status_code, 409)
        self.assertEqual(GoalContribution.objects.count(), 1)

    def test_entry_and_balance_roll_back_together_on_write_failure(self):
        goal = self.goal()
        with patch.object(FinancialGoal, "save", side_effect=RuntimeError("Simulated write failure")):
            with self.assertRaises(RuntimeError):
                self.entry(goal, "50")
        self.assertEqual(GoalContribution.objects.count(), 0)
        self.assertEqual(self.client.get(goal).data["current_amount"], "0.00")

    def test_authentication_and_all_goal_operations_are_owner_scoped(self):
        goal = self.goal(owner=self.other.pk, current_amount="75.00")
        self.assertEqual(self.client.get(goal).data["current_amount"], "0.00")
        self.assertEqual(FinancialGoal.objects.get().owner, self.owner)
        self.assertEqual(APIClient().get(self.url).status_code, 401)
        self.assertEqual(self.other_client.get(self.url).data, [])
        for method, path in [
            ("get", goal), ("patch", goal), ("delete", goal), ("get", goal + "contributions/"),
            ("post", goal + "contributions/"), ("get", goal + "projection/"),
        ]:
            with self.subTest(method=method, path=path):
                self.assertEqual(getattr(self.other_client, method)(path).status_code, 404)
