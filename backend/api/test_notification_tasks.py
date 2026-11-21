from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import OperationalError
from django.test import TestCase, override_settings
from django.utils import timezone

from api.models import (
    Budget, Notification, NotificationCategory, NotificationStockAlert, Stock,
    Subscription, SubscriptionPreferences, Transaction,
)
from api.tasks import (
    check_owner_budgets, check_owner_market, check_owner_renewals, schedule_budgets, schedule_market,
)
from backend.celery import app


class NotificationTaskTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="task-owner")
        self.now = timezone.now()
        self.today = timezone.localdate(self.now)
        self.period = self.today.replace(day=1)

    def budget(self, owner, **fields):
        Budget.objects.create(**{
            "owner": owner, "period": self.period, "currency": "EUR", "category": "groceries",
            "amount": 100, "alert_thresholds": [50], **fields,
        })

    def test_schedule_publishes_only_eligible_owners_and_paginates(self):
        self.budget(self.owner)
        self.budget(self.owner, category="utilities")
        archived = get_user_model().objects.create_user(username="archived")
        disabled = get_user_model().objects.create_user(username="disabled", is_active=False)
        self.budget(disabled)
        self.budget(archived, archived=True)

        with patch("api.tasks.BATCH_SIZE", 1), patch.object(check_owner_budgets, "apply_async") as publish:
            with patch.object(schedule_budgets, "apply_async") as continue_scan:
                self.assertEqual(schedule_budgets.apply().get(), 1)
                self.assertEqual(schedule_budgets.apply(args=(self.owner.pk,)).get(), 0)
        publish.assert_called_once_with(args=(self.owner.pk,), argsrepr="(<redacted>)", kwargsrepr="{}", retry=False)
        continue_scan.assert_called_once_with(args=(self.owner.pk,), argsrepr="(<redacted>)", kwargsrepr="{}", retry=False)

    def test_repeated_checks_share_budget_and_renewal_event_identity(self):
        self.budget(self.owner)
        Transaction.objects.create(
            user=self.owner, timestamp=self.now, amount=-60, particulars="Synthetic",
            currency="EUR", category="groceries",
        )
        SubscriptionPreferences.objects.create(owner=self.owner, renewal_reminders=True)
        Subscription.objects.create(
            owner=self.owner, merchant="Synthetic", normalized_merchant="synthetic",
            estimated_amount=10, currency="EUR", billing_frequency=Subscription.Frequency.MONTHLY,
            next_expected_payment=self.today, detection_confidence=1, status=Subscription.Status.CONFIRMED,
        )
        for task in (check_owner_budgets, check_owner_renewals):
            self.assertEqual(task.apply(args=(self.owner.pk,)).get(), 1)
            self.assertEqual(task.apply(args=(self.owner.pk,)).get(), 0)
        self.assertEqual(set(Notification.objects.values_list("category", flat=True)), {
            NotificationCategory.BUDGET_THRESHOLD, NotificationCategory.SUBSCRIPTION_RENEWAL,
        })

    @override_settings(NOTIFICATION_MARKET_CHECKS_ENABLED=False)
    def test_market_opt_in_guards_scheduler_and_worker(self):
        with patch("api.tasks.generate_stock_alerts") as fetch, patch.object(check_owner_market, "apply_async") as publish:
            self.assertEqual(schedule_market.apply().get(), 0)
            self.assertEqual(check_owner_market.apply(args=(self.owner.pk,)).get(), 0)
        fetch.assert_not_called()
        publish.assert_not_called()

    @override_settings(NOTIFICATION_MARKET_CHECKS_ENABLED=True)
    def test_market_outage_retries_with_sanitized_metadata_and_stale_quote_does_not(self):
        Stock.objects.create(user=self.owner, ticker="AAPL", name="Synthetic", quantity=0, price_per_share=0,
                             purchase_date=self.now)
        NotificationStockAlert.objects.create(
            owner=self.owner, ticker="AAPL", currency="USD", direction="above", target=100,
        )
        with patch("api.services.notification_events.market_quote", return_value={"status": "unavailable"}) as quote:
            with self.assertLogs("api.tasks", level="WARNING") as logs:
                result = check_owner_market.apply(args=(self.owner.pk,))
        self.assertTrue(result.failed())
        self.assertEqual(quote.call_count, 4)
        for delay in (60, 120, 240):
            self.assertTrue(any(f'"delay_seconds": {delay}' in entry for entry in logs.output))
        self.assertIn("retry_exhausted", logs.output[-1])
        self.assertNotIn("AAPL", str(logs.output))
        self.assertFalse(Notification.objects.exists())

        with patch("api.services.notification_events.market_quote", return_value={"status": "stale"}) as quote:
            self.assertEqual(check_owner_market.apply(args=(self.owner.pk,)).get(), 0)
        quote.assert_called_once()

    def test_database_retry_never_logs_raw_error_and_inactive_owner_is_skipped(self):
        with patch("api.tasks.check_budgets", side_effect=OperationalError("Private transaction description")):
            with self.assertLogs("api.tasks", level="WARNING") as logs:
                result = check_owner_budgets.apply(args=(self.owner.pk,))
        self.assertNotIn("Private transaction description", str(result.result) + str(logs.output))
        self.owner.is_active = False
        self.owner.save(update_fields=["is_active"])
        with patch("api.tasks.check_budgets") as evaluate:
            self.assertEqual(check_owner_budgets.apply(args=(self.owner.pk,)).get(), 0)
        evaluate.assert_not_called()

    def test_registered_beat_tasks_and_worker_timeouts(self):
        app.loader.import_default_modules()
        for entry in settings.CELERY_BEAT_SCHEDULE.values():
            self.assertIn(entry["task"], app.tasks)
            self.assertGreaterEqual(entry["schedule"], 60)
        self.assertEqual(app.conf.task_soft_time_limit, 90)
        self.assertEqual(app.conf.task_time_limit, 120)
