from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import product
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from api.models import GroceryCatalogRefresh, GroceryOffer
from api.services.grocery_basket import Pack, WorkLimit, cheapest_packages


class GroceryBasketTests(TestCase):
    url = "/api/grocery/optimize/"
    now = datetime(2026, 11, 21, 12, tzinfo=UTC)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(get_user_model().objects.create_user(username="shopper"))
        self.sequence = 0

    def offer(self, title, retailer="lidl", *, price="2.00", **fields):
        self.sequence += 1
        GroceryCatalogRefresh.objects.get_or_create(
            retailer=retailer,
            defaults={"last_attempt_at": self.now, "last_success_at": self.now, "status": "success"},
        )
        return GroceryOffer.objects.create(**{
            "retailer": retailer, "fingerprint": str(self.sequence), "product_name": title, "normalized_name": title.lower(),
            "price": price, "currency": "EUR", "source_url": "https://example.com/offers",
            "starts_on": self.now.date() - timedelta(days=1), "expires_on": self.now.date() + timedelta(days=1),
            "last_successful_update": self.now, "availability_status": "advertised", **fields,
        })

    def item(self, name, quantity, **fields):
        return {"name": name, "quantity": quantity, **fields}

    def optimize(self, items, **fields):
        with patch("api.services.grocery_basket.timezone.now", return_value=self.now):
            return self.client.post(self.url, {"items": items, **fields}, format="json")

    def test_rounds_to_whole_packages_and_combines_sizes_optimally(self):
        small = self.offer("Ориз 500 г", price="1.30")
        large = self.offer("Rice 1 kg", price="2.40")
        response = self.optimize([self.item("Rice", "1300", unit="g")])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        result = response.data["best_basket"]
        self.assertEqual(result["estimated_total"], "3.70")
        line = result["lines"][0]
        self.assertEqual(line["quantity_purchased"], "1.5")
        self.assertEqual(line["surplus_quantity"], "0.2")
        self.assertEqual({row["offer_id"]: row["count"] for row in line["packages"]}, {small.pk: 1, large.pk: 1})

    def test_missing_and_excluded_offers_have_no_complete_total(self):
        self.offer("Milk 1 l", price="1.70")
        self.offer("Eggs 6 pcs", expires_on=self.now.date() - timedelta(days=1))
        self.offer("Eggs 10 pcs", expires_on=None)
        self.offer("Яйца 6 бр.", retailer="kaufland", requires_membership=True)
        self.offer("Eggs 12 pcs", retailer="fantastico", availability_status="out_of_stock")
        self.offer("Eggs 8 pcs", price=None)
        self.offer("Eggs 7 pcs", currency="BGN")
        self.offer("Eggs 9 pcs", last_successful_update=self.now - timedelta(days=3))

        data = self.optimize([self.item("Milk", 1), self.item("Eggs", 6)]).data
        self.assertIsNone(data["best_basket"])
        self.assertIsNone(data["savings"])
        self.assertEqual(data["unmatched_item_indexes"], [1])
        partial = data["best_partial_basket"]
        self.assertFalse(partial["complete"])
        self.assertEqual(partial["matched_items_subtotal"], "1.70")
        self.assertIsNone(partial["estimated_total"])
        self.assertEqual(data["items"][1]["excluded_offers"]["counts"], {"expired": 1, "uncertain": 2, "unavailable": 4})

    def test_store_limits_overhead_and_savings_use_same_complete_single_store_reference(self):
        self.offer("Milk 1 l", price="2.00")
        self.offer("Eggs 6 pcs", price="5.00")
        self.offer("Мляко 1 л", retailer="kaufland", price="5.00")
        self.offer("Яйца 6 бр.", retailer="kaufland", price="2.00")
        items = [self.item("Milk", 1), self.item("Eggs", 6)]
        data = self.optimize(items, max_stores=2, overhead_per_store="1.00").data
        self.assertEqual(data["best_basket"]["estimated_total"], "6.00")
        self.assertEqual(data["best_basket"]["retailers_used"], ["kaufland", "lidl"])
        self.assertEqual(data["savings"]["reference_total"], "8.00")
        self.assertEqual(data["savings"]["estimated_savings"], "2.00")

        limited = self.optimize(items, max_stores=1, overhead_per_store="1.00").data
        self.assertEqual(limited["best_basket"]["estimated_total"], "8.00")
        self.assertEqual(len(limited["best_basket"]["retailers_used"]), 1)
        overhead = self.optimize(items, max_stores=3, overhead_per_store="4.00").data
        self.assertEqual(overhead["best_basket"]["estimated_total"], "11.00")
        self.assertEqual(len(overhead["best_basket"]["retailers_used"]), 1)
        disabled = self.optimize(items, allow_multi_store=False).data
        self.assertIsNone(disabled["multi_retailer_basket"])
        self.assertEqual(disabled["max_stores"], 1)

    def test_multi_store_solution_can_complete_a_basket_without_a_savings_reference(self):
        self.offer("Milk 1 l")
        self.offer("Rice 1 kg", retailer="kaufland")
        items = [self.item("Milk", 1), self.item("Rice", 1)]
        self.assertIsNone(self.optimize(items, max_stores=1).data["best_basket"])
        result = self.optimize(items, max_stores=2).data
        self.assertEqual(result["best_basket"]["estimated_total"], "4.00")
        self.assertIsNone(result["savings"])

    def test_substitution_and_preferred_brand_rules_exclude_incompatible_products(self):
        preferred = self.offer("Good Milk 1 l", brand="Good", price="3")
        cheaper = self.offer("Other Cow Milk 1 l", brand="Other", price="1")
        self.offer("Almond milk 1 l", price="0.20")
        self.offer("Goat milk 1 l", price="0.10")
        self.offer("Milk 1 kg", price="0.10")
        strict = self.optimize([self.item("Milk 1 l", 1, preferred_brand="Good", allow_substitutions=False)]).data
        self.assertEqual(strict["best_basket"]["lines"][0]["packages"][0]["offer_id"], preferred.pk)
        flexible = self.optimize([self.item("Milk", 1, preferred_brand="Good")]).data
        self.assertEqual(flexible["best_basket"]["lines"][0]["packages"][0]["offer_id"], cheaper.pk)

        cheaper.price = Decimal("3")
        cheaper.save(update_fields=["price"])
        tie = self.optimize([self.item("Milk", 1, preferred_brand="Good")]).data
        self.assertEqual(tie["best_basket"]["lines"][0]["packages"][0]["offer_id"], preferred.pk)

    def test_input_limits_authentication_and_solver_limit(self):
        self.assertEqual(APIClient().post(self.url, {"items": [self.item("Milk", 1)]}, format="json").status_code, 401)
        for items, fields in (
            ([], {}), ([self.item("Milk", 0)], {}), ([self.item("Milk", 1001)], {}),
            ([self.item("Eggs", "0.5")], {}), ([self.item("Milk 1 l", 1, unit="kg")], {}),
            ([self.item("Other product", 1)], {}), ([self.item("Milk", 1)], {"max_stores": 4}),
            ([self.item("Milk", 1)], {"overhead_per_store": "-1"}),
            ([self.item("Milk", 1), self.item("Мляко", 1)], {}),
        ):
            with self.subTest(items=items, fields=fields):
                self.assertEqual(self.optimize(items, **fields).status_code, 400)
        self.offer("Milk 1 l")
        with patch("api.services.grocery_basket.WorkLimit", return_value=WorkLimit(0)):
            self.assertEqual(self.optimize([self.item("Milk", 1)]).status_code, 422)

    def test_solver_matches_exhaustive_optimum_on_small_quantity_datasets(self):
        for sizes, prices in (((2, 3, 4), ("2.3", "3.1", "4.2")), ((3, 5, 7), ("2.0", "2.1", "4.0"))):
            packs = [
                Pack(GroceryOffer(id=index), size, Decimal(price), "exact", False)
                for index, (size, price) in enumerate(zip(sizes, prices, strict=True), 1)
            ]
            for goal in range(1, 13):
                with self.subTest(sizes=sizes, goal=goal):
                    feasible = [
                        (sum((pack.price * count for pack, count in zip(packs, counts, strict=True)), Decimal(0)),
                         sum(counts), sum(pack.units * count for pack, count in zip(packs, counts, strict=True)))
                        for counts in product(range(goal + 1), repeat=len(packs))
                        if sum(pack.units * count for pack, count in zip(packs, counts, strict=True)) >= goal
                    ]
                    cost, units, used = cheapest_packages(packs, goal, WorkLimit())
                    self.assertEqual((cost, sum(count for _, count in used), units), min(feasible))
