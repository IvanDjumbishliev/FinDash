from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import GroceryCatalogRefresh, GroceryOffer, PantryItem, Receipt, ReceiptItem

URL = "/api/pantry/"


class PantryTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="pantry-owner")
        self.other = get_user_model().objects.create_user(username="pantry-other")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def add(self, **fields):
        return self.client.post(URL, {"name": "Milk", "unit": "l", **fields}, format="json")

    def test_receipt_opt_in_idempotency_reference_and_refunds(self):
        offer = GroceryOffer.objects.create(retailer="lidl", fingerprint="source", product_name="Мляко",
                                            last_successful_update=timezone.now())
        receipt = Receipt.objects.create(owner=self.owner, merchant="Test", purchased_at=timezone.now(),
                                         currency="BGN", total=4, source="upload")
        item = ReceiptItem.objects.create(receipt=receipt, original_description="Мляко", quantity=2,
                                         unit="l", line_total=4, product=offer)
        refund = ReceiptItem.objects.create(receipt=receipt, original_description="Хляб", line_total=-2)
        unknown = ReceiptItem.objects.create(receipt=receipt, original_description="Кафе", line_total=2)
        self.assertEqual(self.client.get(URL).data["count"], 0)
        path = URL + "from-receipt/"
        self.assertEqual(self.client.post(path, {"receipt_item": refund.pk}, format="json").status_code, 400)
        first = self.client.post(path, {"receipt_item": item.pk}, format="json")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.data["quantity"], "2.000000")
        self.assertFalse(first.data["quantity_confirmed"])
        self.assertEqual(first.data["product"], offer.pk)
        again = self.client.post(path, {"receipt_item": item.pk}, format="json")
        self.assertEqual((again.status_code, again.data["id"]), (200, first.data["id"]))
        self.assertIsNone(self.client.post(path, {"receipt_item": unknown.pk}, format="json").data["quantity"])
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(path, {"receipt_item": item.pk}, format="json").status_code, 404)
        receipt.delete()
        self.assertIsNone(PantryItem.objects.get(pk=first.data["id"]).receipt_item_id)

    def test_manual_quantities_confirmation_replenishment_and_ownership(self):
        self.assertEqual(self.add(quantity="-1").status_code, 400)
        self.assertEqual(self.add(quantity="1.25", unit="item").status_code, 400)
        self.assertEqual(self.add(quantity_confirmed=True).status_code, 400)
        entry = self.add(quantity="0.5", replenish_below="0.5", quantity_confirmed=True,
                         expires_on="2020-01-01")
        self.assertEqual(entry.status_code, 201)
        self.assertTrue(entry.data["needs_replenishment"])
        path = f"{URL}{entry.data['id']}/"
        updated = self.client.patch(path, {"quantity": "0.75"}, format="json")
        self.assertFalse(updated.data["quantity_confirmed"])
        self.assertFalse(updated.data["needs_replenishment"])
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(URL).data["count"], 0)
        for response in (self.client.get(path), self.client.patch(path, {"quantity": 0}, format="json"),
                         self.client.delete(path), self.client.get(path + "deals/")):
            self.assertEqual(response.status_code, 404)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.delete(path).status_code, 204)

    def test_only_tracked_matching_current_public_deals(self):
        entry = self.add(name="Прясно мляко", quantity="1")
        path = f"{URL}{entry.data['id']}/"
        self.assertEqual(self.client.get(path + "deals/").status_code, 400)
        self.assertEqual(self.client.patch(path, {"track_deals": True}, format="json").status_code, 200)
        now = timezone.now()
        GroceryCatalogRefresh.objects.create(retailer="lidl", last_success_at=now, last_attempt_at=now, status="success")
        for index, (title, unit, membership, expiry) in enumerate((
            ("Milk 1 l", "l", False, 2), ("Oat milk 1 l", "l", False, 2),
            ("Milk 1 l", "l", True, 2), ("Milk 1 l", "l", False, -2),
        )):
            GroceryOffer.objects.create(
                retailer="lidl", fingerprint=str(index), product_name=title, quantity=1, measurement_unit=unit,
                price=2, unit_price=2, currency="EUR", last_successful_update=now,
                starts_on=now.date() - timedelta(days=4), expires_on=now.date() + timedelta(days=expiry),
                availability_status="advertised", requires_membership=membership,
            )
        offers = self.client.get(path + "deals/").data["offers"]
        self.assertEqual([offer["package"]["name"] for offer in offers], ["Milk 1 l"])
        GroceryCatalogRefresh.objects.update(last_success_at=now - timedelta(days=5))
        self.assertEqual(self.client.get(path + "deals/").data["offers"], [])

    def test_recipes_require_confirmed_positive_inventory(self):
        self.add(name="Яйца", quantity=2, unit="item", quantity_confirmed=True)
        cheese = self.add(name="Сирене", quantity="0.2", unit="kg")
        self.assertEqual(self.client.get(URL + "recipes/").data, [])
        self.client.patch(f"{URL}{cheese.data['id']}/", {"quantity_confirmed": True}, format="json")
        self.assertEqual(self.client.get(URL + "recipes/").data[0]["ingredients"], ["Яйца", "Сирене"])
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(URL + "recipes/").data, [])
