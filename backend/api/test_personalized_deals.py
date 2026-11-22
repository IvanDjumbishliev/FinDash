from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import (
    GroceryCatalogRefresh, GroceryOffer, PersonalizedOfferReview, ProductPreference, Receipt, ReceiptItem,
    ShoppingPersonalization,
)
from api.services.receipts import SOFIA, product_identity

URL = "/api/grocery/personalized-deals/"


class PersonalizedDealsTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user(username="deals-owner")
        self.other = users.create_user(username="deals-other")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.now = timezone.now()
        self.day = timezone.localdate(self.now, SOFIA)

    def preferred(self, name, **overrides):
        return ProductPreference.objects.create(**{
            "owner": self.owner, "name": name, "normalized_name": product_identity(name), **overrides,
        })

    def offer(self, name="Milk 1 L", retailer="lidl", **overrides):
        GroceryCatalogRefresh.objects.get_or_create(retailer=retailer, defaults={
            "last_attempt_at": self.now, "last_success_at": self.now, "status": "success",
        })
        return GroceryOffer.objects.create(**{
            "retailer": retailer, "product_name": name, "normalized_name": product_identity(name),
            "price": "2.00", "currency": "EUR", "brand": "Dairy", "quantity": "1.000000", "measurement_unit": "l",
            "pack_count": 1, "availability_status": "advertised", "last_successful_update": self.now,
            "starts_on": self.day, "expires_on": self.day + timedelta(days=2),
            "fingerprint": f"offer-{GroceryOffer.objects.count()}", **overrides,
        })

    def matches(self, **params):
        response = self.client.get(URL, params)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response["Cache-Control"], "no-store")
        return response.data["interests"]

    def review_url(self, preference, offer):
        return f"{URL}{preference.pk}/offers/{offer.pk}/review/"

    def test_bilingual_equivalence_units_sizes_brands_and_priority(self):
        inferred = self.preferred("ориз", source="inferred")
        self.preferred("Прясно мляко", preferred_brand="Dairy", preferred_quantity="1", preferred_unit="l")
        exact = self.offer("Milk 1 L")
        larger = self.offer("Прясно мляко 2 л", quantity="2", price="3.00", retailer="kaufland")
        other_brand = self.offer("Milk 1 L", brand="Other Dairy", retailer="fantastico")
        self.offer("Almond milk 1 L")
        self.offer("Milk 1 kg", measurement_unit="kg")
        matches, rice = self.matches()
        self.assertEqual(rice["id"], inferred.pk)
        self.assertEqual([row["offer_id"] for row in matches["matches"]], [exact.pk, larger.pk, other_brand.pk])
        by_id = {row["offer_id"]: row for row in matches["matches"]}
        self.assertEqual(by_id[exact.pk]["relation"], "exact")
        self.assertEqual(by_id[larger.pk]["relation"], "comparable")
        self.assertEqual(by_id[larger.pk]["unit_price"], "1.500000")
        self.assertFalse(by_id[other_brand.pk]["brand_match"])

    def test_stale_expired_membership_foreign_currency_and_discount_threshold(self):
        self.preferred("milk", minimum_discount=20)
        ordinary = self.offer(discount_percent=20)
        member = self.offer(retailer="kaufland", requires_membership=True, discount_percent=30)
        self.offer(retailer="fantastico", discount_percent=30, last_successful_update=self.now - timedelta(hours=49))
        self.offer(discount_percent=30, expires_on=self.day - timedelta(days=1))
        self.offer(discount_percent=30, currency="BGN")
        self.offer(discount_percent=None)
        self.offer(discount_percent=30, price=None)
        self.assertEqual([row["offer_id"] for row in self.matches()[0]["matches"]], [ordinary.pk])
        self.assertEqual({row["offer_id"] for row in self.matches(membership_retailers=["kaufland"])[0]["matches"]},
                         {ordinary.pk, member.pk})
        self.assertEqual(self.client.get(URL, {"membership_retailers": ["unknown"]}).status_code, 400)

    def test_private_corrections_allow_uncertain_alternatives_and_can_be_reversed(self):
        preference = self.preferred("whole grain bread 500 g")
        uncertain = self.offer("rye bread 500 g", quantity="0.5", measurement_unit="kg")
        incompatible = self.offer("milk 1 l")
        result = self.matches(include_review="true")[0]
        self.assertEqual(result["matches"], [])
        self.assertEqual([row["offer_id"] for row in result["review"]], [uncertain.pk])
        url = self.review_url(preference, uncertain)
        self.assertEqual(self.client.put(url, {"decision": "accept"}, format="json").status_code, 200)
        accepted = self.matches()[0]["matches"][0]
        self.assertEqual(accepted["relation"], "comparable")
        self.assertTrue(accepted["user_reviewed"])
        self.assertEqual(self.client.put(self.review_url(preference, incompatible), {"decision": "accept"}, format="json").status_code, 400)
        self.assertEqual(self.client.put(url, {"decision": "reject"}, format="json").status_code, 200)
        self.assertEqual(self.matches(include_review="true")[0]["review"], [])
        self.client.force_authenticate(self.other)
        self.assertEqual(self.matches(), [])
        self.assertEqual(self.client.put(url, {"decision": "reject"}, format="json").status_code, 404)
        self.assertEqual(self.client.delete(url).status_code, 404)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertEqual(self.matches(include_review="true")[0]["review"][0]["offer_id"], uncertain.pk)

    def test_correction_invalidates_when_product_evidence_changes(self):
        preference = self.preferred("whole grain bread 500 g")
        uncertain = self.offer("rye bread 500 g", quantity="0.5", measurement_unit="kg")
        self.client.put(self.review_url(preference, uncertain), {"decision": "accept"}, format="json")
        self.assertTrue(PersonalizedOfferReview.objects.exists())
        uncertain.product_name = "Oat bread 500 g"
        uncertain.save(update_fields=["product_name"])
        self.assertEqual(self.matches()[0]["matches"], [])
        self.assertEqual(self.matches(include_review="true")[0]["review"][0]["offer_id"], uncertain.pk)

    def test_history_is_opt_in_private_like_for_like_and_currency_specific(self):
        self.preferred("milk")
        self.offer()
        self.preferred("tea", muted=True)
        self.preferred("juice", excluded=True)
        with patch("api.services.personalized_deals.recent_prices") as history:
            self.assertIsNone(self.matches()[0]["matches"][0]["historical"])
            history.assert_not_called()
        ShoppingPersonalization.objects.create(owner=self.owner, automatic_enabled=True)
        for index, (owner, brand, currency) in enumerate(
            [(self.owner, "Dairy", "EUR"), (self.owner, "Different", "EUR"),
             (self.owner, "Dairy", "BGN"), (self.other, "Dairy", "EUR")]
        ):
            receipt = Receipt.objects.create(
                owner=owner, merchant="Store", normalized_merchant="store", currency=currency, total="8",
                source="upload", image_digest=str(index), fingerprint=str(index),
                purchased_at=self.now - timedelta(days=4 - index),
            )
            ReceiptItem.objects.create(receipt=receipt, original_description="Milk", normalized_name="milk",
                                       unit="l", quantity="2", line_total="5" if index == 0 else "8", brand=brand)
        results = self.matches()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["matches"][0]["historical"]["unit_price"], "2.500000")

    def test_ranks_preferred_store_then_unit_price_and_expiration_with_like_for_like_offers(self):
        self.preferred("milk")
        ShoppingPersonalization.objects.create(owner=self.owner, preferred_retailers=["fantastico"])
        preferred = self.offer(retailer="fantastico", price="3")
        cheap = self.offer(retailer="lidl", price="1", expires_on=self.day + timedelta(days=1))
        later = self.offer(retailer="kaufland", price="1")
        higher = self.offer(retailer="lidl", price="2")
        self.assertEqual([row["offer_id"] for row in self.matches()[0]["matches"]],
                         [preferred.pk, cheap.pk, later.pk, higher.pk])


    def test_spelling_similarity_is_comparable_without_claiming_identical(self):
        self.preferred("Organic milk 1 L")
        typo = self.offer("Organik milk 1 L")
        result = self.matches()[0]["matches"]
        self.assertEqual(result[0]["offer_id"], typo.pk)
        self.assertEqual(result[0]["relation"], "comparable")
        self.assertLess(float(result[0]["confidence"]), 1)
