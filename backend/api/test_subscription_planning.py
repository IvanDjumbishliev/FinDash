from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from api.models import Subscription, Transaction
from api.services.subscription_planning import renewal_dates


class RecurrenceTests(SimpleTestCase):
    def test_weekly_skips_elapsed_periods_and_excludes_window_end(self):
        self.assertEqual(
            list(renewal_dates(date(2020, 1, 1), "weekly", date(2026, 11, 18), date(2026, 12, 2))),
            [date(2026, 11, 18), date(2026, 11, 25)],
        )

    def test_monthly_clamping_keeps_the_original_day(self):
        self.assertEqual(
            list(renewal_dates(date(2026, 2, 28), "monthly", date(2026, 2, 26), date(2026, 5, 1), 30)),
            [date(2026, 2, 28), date(2026, 3, 30), date(2026, 4, 30)],
        )

    def test_yearly_leap_day_returns_and_quarterly_month_end_is_preserved(self):
        self.assertEqual(
            list(renewal_dates(date(2024, 2, 29), "yearly", date(2027, 2, 1), date(2028, 3, 1))),
            [date(2027, 2, 28), date(2028, 2, 29)],
        )
        self.assertEqual(
            list(renewal_dates(date(2026, 1, 31), "quarterly", date(2026, 4, 1), date(2026, 8, 1))),
            [date(2026, 4, 30), date(2026, 7, 31)],
        )


class SubscriptionPlanningTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="planner")
        self.other = get_user_model().objects.create_user(username="other-planner")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        clock = patch("api.views.subscriptions.timezone.localdate", return_value=date(2026, 11, 21))
        timezone_mock = clock.start()
        # Transaction date conversion still uses the original timestamp.
        timezone_mock.side_effect = lambda value=None: value.date() if value else date(2026, 11, 21)
        self.addCleanup(clock.stop)

    def subscription(self, merchant, **overrides):
        fields = {
            "owner": self.owner, "merchant": merchant, "normalized_merchant": merchant.lower().replace(" ", ""),
            "currency": "EUR", "estimated_amount": Decimal("12.00"), "billing_frequency": "monthly",
            "next_expected_payment": date(2026, 11, 24), "status": "confirmed",
            "detection_confidence": Decimal("0.9"),
        }
        return Subscription.objects.create(**{**fields, **overrides})

    def test_preferences_are_validated_and_scoped(self):
        url = "/api/subscriptions/preferences/"
        self.assertEqual(self.client.get(url).data, {
            "renewal_reminders": False, "reminder_lead_days": 3, "monthly_summary": False,
        })
        self.assertEqual(self.client.patch(url, {"reminder_lead_days": 31}, format="json").status_code, 400)
        saved = self.client.patch(url, {"renewal_reminders": True, "reminder_lead_days": 0}, format="json")
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(self.client.get(url).data, saved.data)
        self.client.force_authenticate(self.other)
        self.assertFalse(self.client.get(url).data["renewal_reminders"])
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(url).status_code, 401)
        self.assertEqual(self.client.get("/api/subscriptions/planning/").status_code, 401)

    def test_plan_occurrences_due_reminders_and_opt_in_monthly_summary(self):
        record = self.subscription("Weekly", billing_frequency="weekly")
        predicted = self.subscription("Predicted", status="candidate")
        other = self.subscription("Other", owner=self.other)
        inactive = self.subscription("Archived", tracking_status="canceled")
        url = "/api/subscriptions/planning/"
        self.assertIsNone(self.client.get(url).data["summary"])
        self.client.patch("/api/subscriptions/preferences/", {
            "renewal_reminders": True, "reminder_lead_days": 3, "monthly_summary": True,
        }, format="json")
        plan = self.client.get(url).data
        self.assertFalse({other.pk, inactive.pk} & {r["subscription_id"] for r in plan["renewals"]})
        self.assertEqual(
            [r["subscription_id"] for r in plan["renewals"] if r["reminder_due"]],
            [record.pk],
        )
        self.assertGreater(len([r for r in plan["renewals"] if r["subscription_id"] == record.pk]), 10)
        self.assertTrue(any(r["subscription_id"] == predicted.pk for r in plan["renewals"]))
        self.assertEqual(plan["summary"], {
            "month": "2026-11", "renewal_count": 1,
            "totals": [{"currency": "EUR", "remaining": "12.00", "monthly": "52.00", "annual": "624.00"}],
        })

    def test_pause_and_cancel_retain_record_and_stop_projections(self):
        record = self.subscription("Planner")
        url = f"/api/subscriptions/{record.pk}/"
        for status in ("paused", "canceled"):
            update = self.client.patch(url, {"tracking_status": status}, format="json")
            self.assertEqual(update.status_code, 200)
            self.assertEqual(update.data["tracking_status"], status)
            self.assertEqual(self.client.get("/api/subscriptions/planning/").data["renewals"], [])
        record.refresh_from_db()
        self.assertEqual(record.status, "confirmed")
        self.assertEqual(record.estimated_amount, Decimal("12.00"))
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.patch(url, {"tracking_status": "active"}).status_code, 404)

    def test_patterns_flag_overlapping_schedules_and_sustained_price_changes(self):
        monthly = self.subscription("Cloud Service", next_expected_payment=date(2026, 12, 20))
        quarterly = self.subscription(
            "Cloud Service", billing_frequency="quarterly", next_expected_payment=date(2026, 12, 21),
        )
        self.subscription("Cloud Service", currency="USD")
        self.subscription("One-off")
        for merchant, amounts in (
            ("Cloud Service", ["-10", "-10", "-10", "-13", "-13"]),
            ("One-off", ["-10", "-10", "-10", "-10", "-13"]),
        ):
            Transaction.objects.bulk_create([
                Transaction(
                    user=self.owner, particulars=merchant, amount=Decimal(amount), currency="EUR",
                    timestamp=datetime(2026, month, 20, tzinfo=timezone.utc),
                    category=Transaction.Category.BILLS,
                )
                for month, amount in enumerate(amounts, 7)
            ])
        plan = self.client.get("/api/subscriptions/planning/").data
        self.assertEqual(plan["duplicates"], [
            {"subscription_ids": [monthly.pk, quarterly.pk], "overlap_date": "2026-12-20"},
        ])
        self.assertEqual(plan["price_increases"], [
            {"subscription_id": monthly.pk, "previous_amount": "10.00", "recent_amount": "13.00"},
        ])
