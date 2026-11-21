from datetime import date
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from api.models import Budget, FinancialGoal, GoalContribution


class FinancialDatabaseIntegrityTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="integrity-test")

    def test_active_budget_uniqueness_is_enforced_by_database(self):
        data = {"owner": self.owner, "period": date(2026, 11, 1), "amount": "30.00", "currency": "EUR"}
        for category in ("groceries", None):
            with self.subTest(category=category):
                Budget.objects.create(category=category, **data)
                with self.assertRaises(IntegrityError), transaction.atomic():
                    Budget.objects.create(category=category, **data)
                Budget.objects.create(category=category, archived=True, **data)
        self.assertEqual(Budget.objects.filter(owner=self.owner).count(), 4)

    def test_ledger_rejects_duplicate_requests_and_invalid_balance_without_api(self):
        goal = FinancialGoal.objects.create(owner=self.owner, name="Emergency fund", target_amount="50.00", currency="EUR")
        data = {"goal": goal, "kind": "contribution", "amount": "10.00",
                "balance_after": "10.00", "request_id": uuid4()}
        GoalContribution.objects.create(**data)
        with self.assertRaises(IntegrityError), transaction.atomic():
            GoalContribution.objects.create(**data)
        with self.assertRaises(IntegrityError), transaction.atomic():
            GoalContribution.objects.create(**{**data, "request_id": uuid4(), "balance_after": "-0.01"})
        self.assertEqual(goal.contributions.count(), 1)
