from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import GroceryCatalogRefresh, GroceryOffer, Notification, ProductPreference, Receipt, ReceiptItem
from api.services.deal_alerts import evaluate_deal_alerts
from api.services.receipts import SOFIA

URL = "/api/grocery/my-products/"


class MyProductsTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user(username="my-products")
        self.other = users.create_user(username="other-products")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.now = timezone.now()
        self.today = timezone.localdate(self.now, SOFIA)

    def receipt(self, owner, offset, suffix, names):
        receipt = Receipt.objects.create(
            owner=owner, merchant="Test Market", normalized_merchant="test market", currency="EUR",
            purchased_at=self.now - timedelta(days=offset), total="12.00", source="upload",
            fingerprint=suffix, image_digest=suffix,
        )
        for name, total in names:
            ReceiptItem.objects.create(receipt=receipt, original_description=name, normalized_name=name, line_total=total)
        return receipt

    def enable(self):
        response = self.client.patch(URL + "settings/", {"automatic_enabled": True}, format="json")
        self.assertEqual(response.status_code, 200, response.data)

    def decide(self, name, decision):
        return self.client.post(URL + "suggestions/", {"normalized_name": name, "decision": decision}, format="json")

    def add(self, name, **fields):
        response = self.client.post(URL, {"name": name, **fields}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def test_opt_in_suggestions_count_distinct_days_and_skip_sensitive_or_refund_lines(self):
        for offset in (0, 3, 5):
            self.receipt(self.owner, offset, f"r{offset}", [("milk", "3.00"), ("bread", "2.00"),
                                                         ("pregnancy test", "4.00"), ("coffee", "-1.00")])
        self.receipt(self.owner, 0, "same-day", [("milk", "2.50"), ("rice", "1.00")])
        self.receipt(self.owner, 10, "other-day", [("rice", "1.00")])
        self.receipt(self.other, 0, "foreign-rice", [("rice", "1.00")])
        self.receipt(self.owner, 181, "expired", [("rice", "1.00")])
        with patch("api.views.product_preferences.purchase_signals") as signals:
            disabled = self.client.get(URL)
            signals.assert_not_called()
        self.assertFalse(disabled.data["settings"]["automatic_enabled"])
        self.assertEqual(disabled.data["suggestions"], [])
        self.assertEqual(self.decide("milk", "approve").status_code, 403)
        self.enable()
        response = self.client.get(URL)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual([(row["normalized_name"], row["purchase_frequency"]) for row in response.data["suggestions"]],
                         [("bread", 3), ("milk", 3)])
        self.assertFalse(ProductPreference.objects.exists())
        approved = self.decide("milk", "approve")
        rejected = self.decide("bread", "reject")
        self.assertEqual(approved.data["source"], "inferred")
        self.assertTrue(approved.data["favorite"])
        self.assertTrue(rejected.data["excluded"])
        self.assertEqual(self.client.get(URL).data["suggestions"], [])
        self.client.patch(URL + "settings/", {"automatic_enabled": False}, format="json")
        with patch("api.views.product_preferences.purchase_signals") as signals:
            self.assertEqual(self.client.get(URL).data["suggestions"], [])
            signals.assert_not_called()
        self.add("Carrots")
        self.assertEqual(self.client.delete(URL + "suggestions/").status_code, 204)
        self.assertEqual(list(ProductPreference.objects.values_list("name", flat=True)), ["Carrots"])
        self.assertEqual(Receipt.objects.count(), 7)

    def offer(self, retailer="lidl", name="milk", **fields):
        GroceryCatalogRefresh.objects.get_or_create(retailer=retailer, defaults={
            "last_attempt_at": self.now, "last_success_at": self.now, "status": "success",
        })
        return GroceryOffer.objects.create(**{
            "retailer": retailer, "product_name": name, "normalized_name": name, "brand": "Test Brand",
            "price": "2.00", "currency": "EUR", "quantity": "1", "measurement_unit": "l",
            "availability_status": "advertised", "last_successful_update": self.now,
            "starts_on": self.today, "expires_on": self.today + timedelta(days=2),
            "fingerprint": f"{name}-{retailer}-{GroceryOffer.objects.count()}", "discount_percent": 30,
            **fields,
        })

    def test_matching_preferences_categories_exclusion_and_advertised_discount(self):
        milk = self.offer()
        self.offer(retailer="kaufland")
        self.offer(discount_percent=None)
        self.offer(discount_percent=10)
        self.offer(brand="Another")
        self.offer(quantity="2")
        self.offer(expires_on=self.today - timedelta(days=1))
        bread = self.offer(name="хляб")
        preference = self.add("Milk", preferred_brand="test brand", preferred_quantity="1", preferred_unit="l",
                              minimum_discount=20)
        self.client.patch(URL + "settings/", {"preferred_retailers": ["lidl"], "category_interests": ["bread"]}, format="json")
        self.assertEqual({offer["id"] for offer in self.client.get(URL).data["offers"]}, {milk.pk, bread.pk})
        detail = f"{URL}{preference['id']}/"
        for field in ("muted", "excluded"):
            self.client.patch(detail, {field: True}, format="json")
            self.assertEqual([offer["id"] for offer in self.client.get(URL).data["offers"]], [bread.pk])
            self.client.patch(detail, {field: False}, format="json")
        self.assertEqual(self.client.patch(detail, {"preferred_unit": ""}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(detail, {"minimum_discount": 101}, format="json").status_code, 400)
        self.assertEqual(self.client.post(URL, {"name": "MILK"}, format="json").status_code, 400)

    def test_catalog_favorites_are_private_and_client_cannot_set_purchase_evidence(self):
        offer = self.offer()
        response = self.client.post(URL, {
            "product": offer.pk, "source": "inferred", "last_notified_offer": offer.pk, "purchase_frequency": 200,
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["source"], "manual")
        self.assertEqual(response.data["purchase_frequency"], 0)
        self.assertIsNone(response.data["last_notified_offer"])
        detail = f"{URL}{response.data['id']}/"
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(URL).data["products"], [])
        self.assertEqual(self.client.patch(detail, {"favorite": False}, format="json").status_code, 404)
        self.assertEqual(self.client.delete(detail).status_code, 404)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(URL).status_code, 401)

    def test_alert_is_private_idempotent_and_respects_mute_and_discount(self):
        offer = self.offer()
        self.client.patch(URL + "settings/", {"deal_alerts_enabled": True}, format="json")
        preference = self.add("Milk", notifications_enabled=True, minimum_discount=25, muted=True)
        evaluate_deal_alerts(self.owner, now=self.now)
        self.assertFalse(Notification.objects.exists())
        detail = f"{URL}{preference['id']}/"
        self.client.patch(detail, {"muted": False, "minimum_discount": 40}, format="json")
        evaluate_deal_alerts(self.owner, now=self.now)
        self.assertFalse(Notification.objects.exists())
        self.client.patch(detail, {"minimum_discount": 25}, format="json")
        evaluate_deal_alerts(self.owner, now=self.now)
        evaluate_deal_alerts(self.owner, now=self.now)
        notice = Notification.objects.get()
        self.assertEqual(notice.owner, self.owner)
        self.assertEqual(notice.category, "grocery_deal")
        self.assertEqual(ProductPreference.objects.get().last_notified_offer_id, offer.pk)
