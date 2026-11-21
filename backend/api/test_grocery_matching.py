from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings

from api.models import GroceryMatchReview, GroceryOffer
from api.services.grocery_matching import describe, match_offers, review_match


class GroceryMatchingTests(TestCase):
    def offer(self, title, **fields):
        return GroceryOffer(**{
            "product_name": title, "brand": "", "category": "", "currency": "EUR",
            "price": Decimal("2.00"), "retailer": "lidl", **fields,
        })

    def test_bilingual_exact_identity_requires_brand_and_equal_pack(self):
        a = self.offer("Марка Прясно мляко 1 л", brand="Марка")
        b = self.offer("Milk Марка 1000 мл", brand="Марка", retailer="kaufland")
        result = match_offers(a, b)
        self.assertEqual((result.relation, result.method), ("identical", "exact"))
        self.assertEqual(result.left.category, "milk")
        self.assertEqual(result.comparable_prices, (Decimal("2.000000"), Decimal("2.000000")))

        b.brand = "Other"
        b.product_name = "Other Milk 1000 ml"
        self.assertEqual(match_offers(a, b).relation, "comparable")
        unknown_pack = self.offer("Марка Milk", brand="Марка", quantity=Decimal("1"), measurement_unit="l")
        self.assertEqual(match_offers(a, unknown_pack).relation, "comparable")
        a.brand = ""
        a.product_name = "Мляко 1 л"
        self.assertEqual(match_offers(a, self.offer("Milk 1 L")).relation, "comparable")

    def test_eggs_rice_coffee_and_multipacks_compare_on_canonical_quantity(self):
        for first, second, unit, price_a, price_b in (
            ("Яйца 6 бр.", "Eggs pack of 10", "item", "0.333333", "0.200000"),
            ("Ориз 500 г", "Rice 1 kg", "kg", "4.000000", "2.000000"),
            ("Мляно кафе 250 г", "Ground coffee 500 g", "kg", "8.000000", "4.000000"),
            ("Марка Milk 2 x 500 ml", "Марка Milk 1 L", "l", "2.000000", "2.000000"),
        ):
            with self.subTest(first=first, second=second):
                result = match_offers(self.offer(first, brand="Марка"), self.offer(second, brand="Марка"))
                self.assertEqual(result.relation, "comparable")
                self.assertEqual(result.left.unit, unit)
                self.assertEqual(result.comparable_prices, (Decimal(price_a), Decimal(price_b)))

    def test_missing_or_mismatched_units_and_currency(self):
        self.assertEqual(match_offers(self.offer("Milk 1 kg"), self.offer("Milk 1 l")).relation, "incompatible")
        self.assertEqual(match_offers(self.offer("Milk 1 kg"), self.offer("Milk 500 g")).relation, "incompatible")
        self.assertEqual(match_offers(self.offer("Milk"), self.offer("Milk 1 l")).relation, "needs_review")
        conflict = self.offer("Rice 500 g", quantity=Decimal("2"), measurement_unit="kg")
        self.assertEqual(match_offers(conflict, self.offer("Rice 1 kg")).relation, "needs_review")
        self.assertIsNone(describe(conflict).unit_price)
        result = match_offers(self.offer("Rice 1 kg", currency="BGN"), self.offer("Ориз 1 кг"))
        self.assertEqual(result.relation, "comparable")
        self.assertIsNone(result.comparable_prices)
        self.assertIsNone(describe(self.offer("Rice 1 kg", price=None)).unit_price)

    def test_misleading_similar_titles_cannot_be_compared(self):
        forbidden = (
            ("Milk 1 l", "Milk shampoo 1 l"),
            ("Прясно мляко 1 л", "Овесено прясно мляко 1 л"),
            ("Strawberry milk 1 l", "Chocolate milk 1 l"),
            ("Chocolate milk 1 l", "Milk chocolate 1 kg"),
            ("Milk 1 l", "Yogurt 1 l"),
            ("Rice 1 kg", "Rice flour 1 kg"),
            ("Ориз 500 г", "Оризовки 500 г"),
            ("Coffee 1 kg", "Coffee mug 1 kg"),
            ("Ground coffee 500 g", "Instant coffee 500 g"),
            ("Caffeinated coffee 500 g", "Decaf coffee 500 g"),
            ("Кокоши яйца 10 бр.", "Пъдпъдъчи яйца 6 бр."),
            ("Rice 1 kg", "Rice noodles 1 kg"),
            ("Olive oil 1 l", "Sunflower oil 1 l"),
            ("Butter 250 g", "Peanut butter 250 g"),
        )
        for a, b in forbidden:
            with self.subTest(a=a, b=b):
                self.assertEqual(match_offers(self.offer(a), self.offer(b)).relation, "incompatible")
        self.assertEqual(match_offers(self.offer("Rice 1 kg"), self.offer("Rice cooked 1 kg")).relation, "needs_review")
        self.assertEqual(match_offers(self.offer("Eggs pack of 10 x 2"), self.offer("Eggs 10 pcs")).relation, "needs_review")
        self.assertEqual(match_offers(self.offer("Rice 200/500 g"), self.offer("Rice 500 g")).relation, "needs_review")
        self.assertEqual(match_offers(self.offer("Безлактозно мляко 1 l"), self.offer("Milk 1 l")).relation, "needs_review")

    def test_fuzzy_matching_scores_spelling_matches_and_reviews_material_differences(self):
        result = match_offers(self.offer("Coffee smooth classic 500 g"), self.offer("Coffee smooth classsic 1 kg"))
        self.assertEqual((result.relation, result.method), ("comparable", "fuzzy"))
        self.assertGreaterEqual(result.confidence, Decimal("0.88"))
        uncertain = match_offers(self.offer("Coffee smooth classic 500 g"), self.offer("Coffee roast classic 1 kg"))
        self.assertEqual(uncertain.relation, "needs_review")
        self.assertIsNotNone(uncertain.confidence)

    def persist(self, title, identity):
        offer = self.offer(title)
        offer.fingerprint = str(identity)
        offer.normalized_name = title.lower()
        offer.source_url = "https://example.com/offers"
        offer.last_successful_update = datetime(2026, 11, 20, tzinfo=UTC)
        offer.save()
        return offer

    def test_staff_reviews_are_pair_bound_and_expire_on_content_change(self):
        staff = get_user_model().objects.create_user(username="reviewer", is_staff=True)
        member = get_user_model().objects.create_user(username="member")
        first = self.persist("Coffee special classic 500 g", 1)
        second = self.persist("Coffee roast classic 1 kg", 2)
        with self.assertRaises(PermissionDenied):
            review_match(first, second, reviewer=member, decision="approve")
        review_match(second, first, reviewer=staff, decision="approve")
        match = match_offers(first, second)
        self.assertEqual((match.relation, match.method), ("comparable", "human_review"))
        self.assertEqual(GroceryMatchReview.objects.count(), 1)
        second.product_name = "Coffee different roast 1 kg"
        second.save(update_fields=["product_name"])
        self.assertEqual(match_offers(first, second).relation, "needs_review")

        second.product_name = "Coffee mug 1 kg"
        second.save(update_fields=["product_name"])
        self.assertEqual(match_offers(first, second).relation, "incompatible")
        with self.assertRaises(ValueError):
            review_match(first, second, reviewer=staff, decision="approve")

    @override_settings(API_KEY="synthetic-test-key")
    def test_ai_is_optional_validated_cached_and_never_auto_approves(self):
        cache.clear()
        self.addCleanup(cache.clear)
        a, b = self.offer("Coffee breakfast roast 500 g"), self.offer("Coffee espresso roast 1 kg")
        provider = Mock(return_value=SimpleNamespace(text='{"suggestion":"cheapest"}'))
        with patch("api.services.grocery_match_ai.client", SimpleNamespace(models=SimpleNamespace(generate_content=provider))):
            self.assertIsNone(match_offers(a, b).ai_suggestion)
            provider.assert_not_called()
            self.assertIsNone(match_offers(a, b, ai_assist=True).ai_suggestion)
            provider.return_value.text = '{"suggestion":"comparable"}'
            match = match_offers(a, b, ai_assist=True)
            self.assertEqual(match.relation, "needs_review")
            self.assertEqual(match.ai_suggestion, "comparable")
            self.assertEqual(match_offers(b, a, ai_assist=True).ai_suggestion, "comparable")
            self.assertEqual(match_offers(a, self.offer("Coffee machine 1 kg"), ai_assist=True).relation, "incompatible")
            self.assertEqual(provider.call_count, 2)
