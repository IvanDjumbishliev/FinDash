from datetime import datetime, time, timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from api.models import (
    GroceryCatalogRefresh, GroceryOffer, Notification, NotificationPreference, ProductPreference,
    Receipt, ReceiptItem, ShoppingPersonalization, TrackedGroceryOffer, UserProfile,
)
from api.services.deal_alerts import evaluate_deal_alerts
from api.services.notifications import purge_notifications
from api.services.receipts import SOFIA
from api.tasks import check_owner_grocery_deals, schedule_grocery_deals

PRODUCTS = "/api/grocery/my-products/"
INBOX = "/api/notifications/"


class DealNotificationTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user(username="alert-owner")
        self.other = users.create_user(username="alert-other")
        UserProfile.objects.update_or_create(user=self.owner, defaults={"timezone": "Europe/Sofia"})
        self.now = datetime(2026, 11, 23, 10, 0, tzinfo=SOFIA)
        self.profile = ShoppingPersonalization.objects.create(owner=self.owner, deal_alerts_enabled=True)
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def preference(self, name="milk", **fields):
        return ProductPreference.objects.create(**{
            "owner": self.owner, "name": name, "normalized_name": name,
            "notifications_enabled": True, **fields,
        })

    def offer(self, name="milk", retailer="lidl", **fields):
        GroceryCatalogRefresh.objects.get_or_create(retailer=retailer, defaults={
            "last_attempt_at": self.now, "last_success_at": self.now, "status": "success",
        })
        return GroceryOffer.objects.create(**{
            "retailer": retailer, "product_name": name, "normalized_name": name,
            "brand": "Test Dairy", "quantity": "1", "measurement_unit": "l",
            "pack_count": 1, "price": "2.00", "currency": "EUR", "availability_status": "advertised",
            "last_successful_update": self.now, "starts_on": self.now.date(),
            "expires_on": self.now.date() + timedelta(days=1),
            "fingerprint": f"offer-{GroceryOffer.objects.count()}", **fields,
        })

    def run_engine(self, now=None, owner=None):
        return evaluate_deal_alerts(owner or self.owner, now=now or self.now)

    def test_requires_account_product_and_category_opt_in_then_deduplicates(self):
        self.offer()
        preference = self.preference(notifications_enabled=False)
        self.profile.deal_alerts_enabled = False
        self.profile.save()
        self.assertEqual(self.run_engine(), 0)
        self.profile.deal_alerts_enabled = True
        self.profile.save()
        self.assertEqual(self.run_engine(), 0)
        preference.notifications_enabled = True
        preference.save()
        category = NotificationPreference.objects.create(owner=self.owner, categories={"grocery_deal": False})
        self.assertEqual(self.run_engine(), 0)
        category.categories = {"grocery_deal": True}
        category.save()
        self.assertEqual(self.run_engine(), 1)
        self.assertEqual(self.run_engine(), 0)
        preference.refresh_from_db()
        self.assertIsNotNone(preference.last_notified_offer_id)
        self.assertEqual(Notification.objects.count(), 1)
        with override_settings(NOTIFICATION_RETENTION_DAYS=0):
            self.assertEqual(purge_notifications(now=self.now + timedelta(days=100)), 1)
        self.assertEqual(self.run_engine(), 0)

    def test_threshold_historical_reason_and_owner_visibility(self):
        self.offer(price="2.00")
        self.preference(favorite=False, alert_price="2.10", alert_currency="EUR")
        self.preference(owner=self.other, favorite=True)
        for owner, amount in [(self.owner, "6.00"), (self.other, "10.00")]:
            receipt = Receipt.objects.create(
                owner=owner, merchant="Synthetic Store", currency="EUR", source="upload", total=amount,
                image_digest=str(owner.pk), fingerprint=str(owner.pk), purchased_at=self.now - timedelta(days=1),
            )
            ReceiptItem.objects.create(receipt=receipt, original_description="milk", normalized_name="milk",
                                       brand="Test Dairy", unit="l", quantity="2", line_total=amount)
        preference = ProductPreference.objects.get(owner=self.owner)
        ProductPreference.objects.filter(pk=preference.pk).update(alert_price=None, alert_currency="")
        with patch("api.services.personalized_deals.recent_prices") as history:
            self.assertEqual(self.run_engine(), 0)
            history.assert_not_called()
        ProductPreference.objects.filter(pk=preference.pk).update(alert_price="2.10", alert_currency="EUR")
        self.profile.automatic_enabled = True
        self.profile.save()
        self.assertEqual(self.run_engine(), 1)
        self.assertEqual(self.run_engine(owner=self.other), 0)
        result = self.client.get(INBOX).data["results"][0]["payload"]["deals"][0]
        self.assertEqual((result["product"], result["retailer"], result["price"]), ("milk", "Lidl", "2.00"))
        self.assertEqual(result["expires_on"], "2026-11-24")
        self.assertEqual(len(result["reasons"]), 2)
        self.assertIn("2.10 EUR", result["reasons"][0])
        self.assertIn("3 EUR/l", result["reasons"][1])
        self.assertNotIn("5 EUR/l", str(result))
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(INBOX).data["results"], [])

    def test_price_changes_can_cross_a_threshold_once(self):
        offer = self.offer(price="2.20")
        self.preference(favorite=False, alert_price="2.00", alert_currency="EUR")
        self.assertEqual(self.run_engine(), 0)
        offer.price = "2.00"
        offer.save(update_fields=["price"])
        self.assertEqual(self.run_engine(), 1)
        self.assertEqual(self.run_engine(), 0)
        offer.price = "1.90"
        offer.save(update_fields=["price"])
        self.assertEqual(self.run_engine(), 1)
        self.assertEqual(self.run_engine(), 0)

    def test_stale_expired_membership_and_retailer_filters(self):
        preference = self.preference()
        self.profile.preferred_retailers = ["lidl"]
        self.profile.save()
        self.offer(retailer="kaufland")
        self.offer(requires_membership=True)
        self.offer(expires_at=self.now)
        self.offer(expires_on=self.now.date() - timedelta(days=1))
        stale = self.offer(last_successful_update=self.now - timedelta(hours=49))
        TrackedGroceryOffer.objects.create(preference=preference, offer=stale)
        self.assertEqual(self.run_engine(), 0)
        self.assertFalse(Notification.objects.exists())

    def test_tracked_offer_expiry_is_separate_and_checked_at_delivery(self):
        offer = self.offer(expires_at=self.now + timedelta(hours=25))
        preference = self.preference()
        TrackedGroceryOffer.objects.create(preference=preference, offer=offer)
        self.assertEqual(self.run_engine(), 1)
        near = self.now + timedelta(hours=2)
        self.assertEqual(self.run_engine(near), 1)
        self.assertEqual(self.run_engine(near), 0)
        self.assertEqual(self.run_engine(self.now + timedelta(hours=25)), 0)
        reasons = [notice.payload["deals"][0]["reasons"][0] for notice in Notification.objects.all()]
        self.assertIn("An offer you tracked ends within 24 hours.", reasons)

    def test_daily_digest_waits_for_quiet_hours_and_occurs_once_per_day(self):
        self.profile.deal_delivery = "digest"
        self.profile.digest_time = time(8)
        self.profile.quiet_start = time(22)
        self.profile.quiet_end = time(9)
        self.profile.save()
        self.preference()
        self.preference("bread")
        self.offer()
        self.offer("bread", quantity="0.5", measurement_unit="kg")
        self.assertEqual(self.run_engine(self.now.replace(hour=8)), 0)
        self.assertEqual(self.run_engine(), 1)
        notice = Notification.objects.get()
        self.assertEqual(notice.payload["kind"], "digest")
        self.assertEqual(len(notice.payload["deals"]), 2)
        self.offer(price="1.95")
        self.assertEqual(self.run_engine(self.now + timedelta(minutes=30)), 0)
        self.assertEqual(self.run_engine(self.now + timedelta(days=1)), 1)
        self.assertEqual(Notification.objects.count(), 2)

    def test_validate_settings_thresholds_and_tracking_scope(self):
        preference = self.preference()
        offer = self.offer()
        detail = f"{PRODUCTS}{preference.pk}/"
        with patch("api.views.product_preferences.timezone.now", return_value=self.now):
            self.assertEqual(self.client.post(detail + "tracked-offers/", {"offer_id": offer.pk}, format="json").status_code, 201)
            self.assertEqual(self.client.post(detail + "tracked-offers/", {"offer_id": offer.pk}, format="json").status_code, 201)
        self.assertEqual(TrackedGroceryOffer.objects.count(), 1)
        self.assertEqual(self.client.patch(detail, {"alert_price": "2.10"}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(PRODUCTS + "settings/", {"quiet_start": "20:00"}, format="json").status_code, 400)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.delete(detail + f"tracked-offers/{offer.pk}/").status_code, 404)

    @override_settings(GROCERY_CATALOG_RETAILERS={"lidl"})
    def test_refresh_enqueues_only_on_success_and_scheduler_uses_eligible_owners(self):
        self.preference()
        with patch("api.services.grocery_catalog.ADAPTERS", {"lidl": lambda **_: [{
            "name": "milk", "_catalog": {"source_url": "https://example.com", "amount": "2.00", "currency": "EUR"},
        }]}), patch("api.tasks.enqueue") as enqueue:
            with self.captureOnCommitCallbacks(execute=True):
                call_command("refresh_grocery_catalog", "lidl", stdout=StringIO())
            enqueue.assert_called_once_with(schedule_grocery_deals)
            enqueue.reset_mock()
            with self.captureOnCommitCallbacks(execute=True):
                call_command("refresh_grocery_catalog", "lidl", stdout=StringIO())
            enqueue.assert_not_called()
            self.assertEqual(schedule_grocery_deals.run(), 1)
            enqueue.assert_called_once_with(check_owner_grocery_deals, self.owner.pk)
