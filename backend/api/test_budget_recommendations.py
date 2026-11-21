import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils.timezone import now
from rest_framework.test import APIClient

from api.models import Budget, BudgetSuggestionReview, Transaction

GENERATE = "/api/budgets/recommendations/"
APPLY = f"{GENERATE}apply/"


@override_settings(API_KEY="test-configured")
class BudgetRecommendationTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="recommendation-owner")
        self.other = get_user_model().objects.create_user(username="recommendation-other")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def record(self, month, amount, **overrides):
        fields = {
            "user": self.owner, "currency": "EUR", "category": "groceries",
            "particulars": "Bank transaction details stay local",
        }
        return Transaction.objects.create(
            **{**fields, **overrides},
            timestamp=datetime(2025, month, 12, tzinfo=timezone.utc), amount=Decimal(amount),
        )

    def history(self, **overrides):
        for month, amount in [(8, "-60"), (9, "-80"), (10, "-100")]:
            self.record(month, amount, **overrides)

    def generate(self, **overrides):
        return self.client.post(GENERATE, {"period": "2025-11", **overrides}, format="json")

    def apply(self, review, categories, **overrides):
        return self.client.post(APPLY, {
            "review_id": review, "categories": categories, "confirmed": True, **overrides,
        }, format="json")

    def create_budget(self):
        return Budget.objects.create(
            owner=self.owner, period=datetime(2025, 11, 1).date(), currency="EUR",
            category="groceries", amount=Decimal("99"), alert_thresholds=[65],
        )

    def test_calculations_use_completed_months_and_existing_spending_rules(self):
        self.history()
        self.record(8, "-15", particulars="Transfer to savings")
        self.record(8, "-6")
        self.record(8, "6", particulars="Refund")
        self.record(11, "-900")
        self.record(6, "-15", currency="USD")
        self.record(9, "-999", user=self.other)
        response = self.generate()
        self.assertEqual(response.status_code, 200, response.data)
        item, = response.data["recommendations"]
        self.assertEqual(item["currency"], "EUR")
        self.assertEqual(item["suggested_amount"], "88.16")
        self.assertEqual(item["statistics"], {
            "months_analyzed": 3, "average": "80.00", "standard_deviation": "16.33",
            "baseline": "80.00", "variability_buffer": "8.16", "trend": "increasing",
            "monthly_spending": [
                {"period": f"2025-{month:02}-01", "amount": amount}
                for month, amount in [(8, "60.00"), (9, "80.00"), (10, "100.00")]
            ],
        })
        self.assertFalse(Budget.objects.exists())

    def test_complete_history_includes_zero_category_months_and_caps_buffer(self):
        self.history()
        self.record(5, "-10", category="shopping")
        self.record(7, "-10", category="shopping")
        item, = self.generate().data["recommendations"]
        self.assertEqual(item["statistics"]["months_analyzed"], 5)
        self.assertEqual(item["statistics"]["average"], "48.00")
        self.assertEqual(item["statistics"]["baseline"], "80.00")
        self.assertEqual(item["statistics"]["variability_buffer"], "12.00")
        self.assertEqual(item["suggested_amount"], "92.00")

    def test_missing_and_mixed_history_does_not_allocate_budgets(self):
        self.record(8, "-15")
        self.record(9, "-20", currency="USD")
        self.record(10, "-25")
        response = self.generate()
        self.assertEqual(response.data["status"], "insufficient_history")
        self.assertIsNone(response.data["review_id"])
        self.assertFalse(BudgetSuggestionReview.objects.exists())

    @patch("api.services.budget_explanations.client")
    def test_ai_requires_explicit_boolean_and_only_receives_aggregate_data(self, client):
        self.history()
        self.assertEqual(self.generate().data["ai_status"], "not_requested")
        self.assertEqual(self.generate(use_gemini="true").status_code, 400)
        self.assertEqual(self.generate(use_gemini=False).data["ai_status"], "not_requested")
        client.models.generate_content.assert_not_called()

        client.models.generate_content.return_value = SimpleNamespace(
            text='[{"index": 0, "explanation": "This estimate includes a variability buffer."}]'
        )
        result = self.generate(use_gemini=True)
        self.assertEqual(result.data["ai_status"], "used")
        self.assertIn("ai_explanation", result.data["recommendations"][0])
        data = client.models.generate_content.call_args.kwargs["contents"][1]
        self.assertNotIn("Bank transaction details", data)
        self.assertNotIn("2025-", data)
        self.assertNotIn("monthly_spending", data)
        self.assertEqual(set(json.loads(data)[0]), {"index", "category", "currency", "suggested_amount", "statistics"})

    @patch("api.services.budget_explanations.client")
    def test_malformed_or_unavailable_ai_keeps_statistical_suggestions(self, client):
        self.history()
        for fake in (
            SimpleNamespace(text="bad json"),
            SimpleNamespace(text='[{"index": 0, "explanation": null}]'),
            SimpleNamespace(text='[{"index": true, "explanation": "wrong"}]'),
            SimpleNamespace(text='[{"index": 1, "explanation": "out of range"}]'),
        ):
            client.models.generate_content.return_value = fake
            result = self.generate(use_gemini=True)
            self.assertEqual(result.data["ai_status"], "unavailable")
            item, = result.data["recommendations"]
            self.assertEqual(item["suggested_amount"], "88.16")
            self.assertNotIn("ai_explanation", item)
        client.models.generate_content = Mock(side_effect=TimeoutError)
        self.assertEqual(self.generate(use_gemini=True).data["ai_status"], "unavailable")
        self.assertFalse(Budget.objects.exists())

    def test_only_confirmed_selected_categories_apply_and_keep_settings(self):
        self.history()
        self.history(category="bills")
        budget = self.create_budget()
        review = self.generate().data["review_id"]
        self.assertEqual(self.apply(review, ["groceries"], confirmed=False).status_code, 400)
        self.assertEqual(self.apply(review, ["groceries"], confirmed="true").status_code, 400)
        self.assertEqual(self.apply(review, ["shopping"]).status_code, 400)
        budget.refresh_from_db()
        self.assertEqual(budget.amount, Decimal("99.00"))
        response = self.apply(review, ["groceries"])
        self.assertEqual(response.status_code, 200, response.data)
        budget.refresh_from_db()
        self.assertEqual(budget.amount, Decimal("88.16"))
        self.assertEqual(budget.alert_thresholds, [65])
        self.assertEqual(Budget.objects.count(), 1)
        self.assertEqual(self.apply(review, ["bills"]).status_code, 404)

    def test_new_budget_is_created_only_after_approval(self):
        self.history()
        review = self.generate().data["review_id"]
        self.assertFalse(Budget.objects.exists())
        self.assertEqual(self.apply(review, ["groceries"]).status_code, 200)
        self.assertEqual(Budget.objects.get(owner=self.owner).amount, Decimal("88.16"))

    def test_changed_budget_rejects_entire_batch_and_expired_or_other_reviews_are_private(self):
        self.history()
        self.history(category="bills")
        budget = self.create_budget()
        review = self.generate().data["review_id"]
        self.client.force_authenticate(self.other)
        self.assertEqual(self.apply(review, ["groceries"]).status_code, 404)
        self.client.force_authenticate(self.owner)
        budget.amount = Decimal("200")
        budget.save()
        self.assertEqual(self.apply(review, ["bills", "groceries"]).status_code, 409)
        self.assertEqual(Budget.objects.count(), 1)
        BudgetSuggestionReview.objects.filter(pk=review).update(expires_at=now() - timedelta(minutes=1))
        self.assertEqual(self.apply(review, ["groceries"]).status_code, 404)
        self.client.force_authenticate(None)
        self.assertEqual(self.generate().status_code, 401)
        self.assertEqual(self.apply(review, ["groceries"]).status_code, 401)
