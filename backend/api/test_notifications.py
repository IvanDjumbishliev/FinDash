from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import transaction
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from api.models import (
    Budget, Notification, NotificationCategory as Category, NotificationEvent, NotificationStockAlert,
    Stock, Subscription, SubscriptionPreferences, Transaction,
)
from api.services.notification_events import (
    check_budgets, generate_renewal_alerts, generate_stock_alerts, transaction_recorded,
)
from api.services.notifications import after_commit, notify


class NotificationTests(TestCase):
    url = "/api/notifications/"
    moment = datetime(2026, 11, 21, 10, tzinfo=UTC)

    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user(username="inbox-owner")
        self.other = users.objects.create_user(username="other-inbox-owner")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.other_client = APIClient()
        self.other_client.force_authenticate(self.other)

    def record(self, amount, timestamp=None, **fields):
        return Transaction.objects.create(**{
            "user": self.owner, "amount": amount, "timestamp": timestamp or self.moment, "currency": "EUR",
            "category": "groceries", "particulars": "Synthetic sensitive description", **fields,
        })

    def test_read_unread_dismiss_mark_all_and_ownership(self):
        first = notify(self.owner.pk, Category.STATEMENT_IMPORT, "same-event")
        notify(self.other.pk, Category.STATEMENT_IMPORT, "same-event")
        second = notify(self.owner.pk, Category.FINANCIAL_REPORT, "report")
        self.assertEqual(APIClient().get(self.url).status_code, 401)
        self.assertEqual(self.other_client.patch(f"{self.url}{first.pk}/", {"read": True}, format="json").status_code, 404)
        inbox = self.client.get(self.url)
        self.assertEqual(inbox.headers["Cache-Control"], "no-store")
        self.assertEqual(inbox.data["unread_count"], 2)
        self.assertEqual({row["id"] for row in inbox.data["results"]}, {first.pk, second.pk})
        self.assertNotIn("same-event", str(inbox.data))
        own = f"{self.url}{first.pk}/"
        self.assertEqual(self.client.patch(own, {"read": "true"}, format="json").status_code, 400)
        self.assertTrue(self.client.patch(own, {"read": True}, format="json").data["read"])
        self.assertFalse(self.client.patch(own, {"read": False}, format="json").data["read"])
        self.assertTrue(self.client.patch(own, {"dismissed": True}, format="json").data["dismissed"])
        self.assertEqual(self.client.get(self.url, {"unread": "true"}).data["count"], 1)
        self.assertEqual(self.client.post(self.url + "mark-all-read/").data["updated"], 1)
        self.assertEqual(self.client.get(self.url, {"include_dismissed": "true"}).data["count"], 2)
        self.assertEqual(self.other_client.get(self.url).data["unread_count"], 1)

    @override_settings(NOTIFICATION_RETENTION_DAYS=7)
    def test_retention_hides_and_purges_inbox_entries_without_replaying_events(self):
        item = notify(self.owner.pk, Category.BUDGET_THRESHOLD, "old-budget")
        Notification.objects.filter(pk=item.pk).update(created_at=self.moment - timedelta(days=8))
        with patch("api.services.notifications.timezone.now", return_value=self.moment):
            self.assertEqual(self.client.get(self.url).data["count"], 0)
            self.assertEqual(self.client.patch(f"{self.url}{item.pk}/", {"read": True}, format="json").status_code, 404)
            call_command("process_notifications", stdout=StringIO())
        self.assertFalse(Notification.objects.exists())
        self.assertTrue(NotificationEvent.objects.exists())
        self.assertIsNone(notify(self.owner.pk, Category.BUDGET_THRESHOLD, "old-budget"))
        self.assertFalse(Notification.objects.exists())

    def test_partial_preferences_stop_new_events_and_reject_forged_watchlist_tickers(self):
        address = self.url + "preferences/"
        result = self.client.get(address)
        self.assertTrue(result.data["categories"][Category.STATEMENT_IMPORT])
        self.assertEqual(self.client.patch(address, {"categories": {"invented": False}}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(address, {"categories": {Category.STATEMENT_IMPORT: "false"}}, format="json").status_code, 400)
        result = self.client.patch(address, {"categories": {Category.STATEMENT_IMPORT: False}}, format="json")
        self.assertFalse(result.data["categories"][Category.STATEMENT_IMPORT])
        self.assertTrue(result.data["categories"][Category.FINANCIAL_REPORT])
        self.assertTrue(self.other_client.get(address).data["categories"][Category.STATEMENT_IMPORT])
        self.assertIsNone(notify(self.owner.pk, Category.STATEMENT_IMPORT, "disabled"))
        self.assertFalse(NotificationEvent.objects.exists())
        self.assertIsNotNone(notify(self.owner.pk, Category.FINANCIAL_REPORT, "enabled"))
        Stock.objects.create(user=self.other, ticker="AAPL", name="Other", quantity=0, price_per_share=0,
                             purchase_date=self.moment)
        rejected = self.client.patch(address, {"stock_alerts": [
            {"ticker": "AAPL", "currency": "USD", "target": "100", "direction": "above"},
        ]}, format="json")
        self.assertEqual(rejected.status_code, 400)

    def test_transaction_events_emit_budget_and_unusual_spending_without_private_payloads(self):
        budget = Budget.objects.create(owner=self.owner, period=self.moment.date().replace(day=1),
                                       currency="EUR", category="groceries", amount=100, alert_thresholds=[50, 80, 100])
        for offset in range(11, 19):
            self.record("-10", self.moment - timedelta(days=offset))
        self.record("-15000", self.moment, particulars="Internal transfer")
        with patch("api.services.notification_events.timezone.now", return_value=self.moment):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post("/api/transactions/", {
                    "timestamp": self.moment.isoformat(), "amount": "-120", "currency": "EUR",
                    "category": "groceries", "particulars": "Secret grocery item",
                }, format="json")
            self.assertEqual(response.status_code, 201)
            transaction_recorded(self.owner.pk, response.data["id"])
            check_budgets(self.owner.pk, {budget.period})
            self.assertEqual(Notification.objects.filter(category=Category.UNUSUAL_SPENDING).count(), 1)
            self.assertEqual(Notification.objects.filter(category=Category.BUDGET_THRESHOLD).count(), 3)
            inbox = self.client.get(self.url).data
        for secret in ("Secret grocery item", "15000", "120.00", "Synthetic sensitive"):
            self.assertNotIn(secret, str(inbox))

    def test_rolled_back_callbacks_do_not_create_events(self):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with transaction.atomic():
                after_commit(notify, self.owner.pk, Category.FINANCIAL_REPORT, "rolled back")
                transaction.set_rollback(True)
        self.assertEqual(callbacks, [])
        self.assertFalse(Notification.objects.exists())

    def test_statement_confirmation_and_report_generation_notify_once(self):
        preview = self.client.post("/api/bank-statement/preview/", {
            "file": SimpleUploadedFile("statement.csv", b"Date,Description,Amount,Currency\n2026-11-21,Test payment,-12,EUR\n", content_type="text/csv"),
        }, format="multipart")
        self.assertEqual(preview.status_code, 201)
        self.assertFalse(Notification.objects.exists())
        confirm = f"/api/bank-statement/imports/{preview.data['id']}/confirm/"
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.client.post(confirm).status_code, 200)
            self.assertEqual(self.client.post(confirm).status_code, 200)
        self.assertEqual(Notification.objects.filter(category=Category.STATEMENT_IMPORT).count(), 1)
        with patch("api.services.reports.timezone.now", return_value=self.moment):
            with self.captureOnCommitCallbacks(execute=True):
                for _ in range(2):
                    self.assertEqual(self.client.post("/api/reports/", {"month": "2026-11"}, format="json").status_code, 200)
        self.assertEqual(Notification.objects.filter(category=Category.FINANCIAL_REPORT).count(), 1)

    def test_renewal_generation_honors_lead_days_tracking_and_preferences(self):
        SubscriptionPreferences.objects.create(owner=self.owner, renewal_reminders=True, reminder_lead_days=3)
        for status, tracking, offset in (("confirmed", "active", 2), ("confirmed", "paused", 1),
                                          ("candidate", "active", 1), ("confirmed", "active", 4)):
            Subscription.objects.create(
                owner=self.owner, merchant=f"Service {offset}", normalized_merchant=f"service-{status}-{tracking}-{offset}",
                estimated_amount=10, currency="EUR", billing_frequency="monthly", status=status, tracking_status=tracking,
                next_expected_payment=self.moment.date() + timedelta(days=offset), detection_confidence=Decimal("0.8"),
            )
        self.assertEqual(generate_renewal_alerts(self.owner, now=self.moment), 1)
        self.assertEqual(generate_renewal_alerts(self.owner, now=self.moment), 0)
        self.client.patch(self.url + "preferences/", {"categories": {Category.SUBSCRIPTION_RENEWAL: False}}, format="json")
        self.assertEqual(generate_renewal_alerts(self.owner, now=self.moment + timedelta(days=2)), 0)

    def test_stock_crossings_require_fresh_same_currency_prices_and_rearm(self):
        Stock.objects.create(user=self.owner, ticker="AAPL", name="Apple", quantity=0, price_per_share=0,
                             purchase_date=self.moment)
        prefs = self.url + "preferences/"
        payload = {"stock_alerts": [{"ticker": "aapl", "currency": "usd", "direction": "above", "target": "100.00"}]}
        result = self.client.patch(prefs, payload, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        original = NotificationStockAlert.objects.get(owner=self.owner)

        def quote(price, minutes, currency="USD", status="quoted"):
            return {"price": Decimal(price), "timestamp": self.moment - timedelta(minutes=minutes),
                    "currency": currency, "status": status}

        with patch("api.services.notification_events.market_quote") as market:
            for observation, expected in (
                (quote("500", 2200), 0), (quote("500", 70, "EUR"), 0),
                (quote("500", 70, status="stale"), 0), (quote("98", 60), 0), (quote("100", 50), 1),
                (quote("103", 40), 0), (quote("99", 30), 0), (quote("105", 20), 1), (quote("105", 20), 0),
                (quote("105", 40), 0),
            ):
                market.return_value = observation
                self.assertEqual(generate_stock_alerts(self.owner, now=self.moment), expected)
            self.client.patch(prefs, payload, format="json")
            self.assertEqual(NotificationStockAlert.objects.get(owner=self.owner).pk, original.pk)
            self.client.patch(prefs, {"categories": {Category.STOCK_THRESHOLD: False}}, format="json")
            market.reset_mock()
            self.assertEqual(generate_stock_alerts(self.owner, now=self.moment), 0)
            market.assert_not_called()
        self.assertEqual(Notification.objects.filter(category=Category.STOCK_THRESHOLD).count(), 2)
