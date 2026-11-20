from datetime import datetime, timezone
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from api.models import Subscription, Transaction


class SubscriptionTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="subscriber")
        self.other = get_user_model().objects.create_user(username="another-subscriber")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def record(
        self, dates, merchant="Cloud Service", amounts=None, currency="EUR", user=None
    ):
        if isinstance(merchant, str):
            merchant = [merchant] * len(dates)
        Transaction.objects.bulk_create(
            Transaction(
                user=user or self.owner,
                timestamp=datetime.fromisoformat(day).replace(tzinfo=timezone.utc),
                amount=Decimal(amount),
                particulars=description,
                currency=currency,
                category=Transaction.Category.BILLS,
            )
            for day, amount, description in zip(
                dates, amounts or ["-9.99"] * len(dates), merchant
            )
        )

    def detect(self):
        response = self.client.post("/api/subscriptions/detect/")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def test_month_end_recurrence_with_merchant_variations(self):
        self.record(
            ["2024-01-31", "2024-02-29", "2024-03-31"],
            [
                "POS * Cloud-Service.com REF #1234",
                "CLOUD SERVICE 8891",
                "Card payment: Cloud Service",
            ],
        )
        (result,) = self.detect()
        self.assertEqual(result["normalized_merchant"], "cloudservice")
        self.assertEqual(result["estimated_amount"], "9.99")
        self.assertEqual(result["billing_frequency"], "monthly")
        self.assertEqual(result["next_expected_payment"], "2024-04-30")
        self.assertEqual(result["status"], "candidate")
        self.assertGreater(Decimal(result["detection_confidence"]), Decimal("0.80"))

    def test_billing_dates_and_small_amounts_can_vary(self):
        self.record(
            ["2024-01-10", "2024-02-12", "2024-03-09", "2024-04-11"],
            amounts=["-10.00", "-10.20", "-9.80", "-10.15"],
        )
        (result,) = self.detect()
        self.assertEqual(result["estimated_amount"], "10.08")
        self.assertEqual(result["next_expected_payment"], "2024-05-10")
        self.assertLess(Decimal(result["detection_confidence"]), Decimal("0.96"))

    def test_posting_delay_across_month_boundary_keeps_calendar_cadence(self):
        self.record(["2024-01-31", "2024-03-01", "2024-03-31"])
        (result,) = self.detect()
        self.assertEqual(result["next_expected_payment"], "2024-04-30")
        self.assertEqual(result["billing_frequency"], "monthly")

    def test_weekly_quarterly_and_yearly_patterns(self):
        self.record(["2024-01-05", "2024-01-12", "2024-01-19"], "Weekly Club")
        self.record(["2024-01-31", "2024-04-30", "2024-07-31"], "Quarterly Club")
        self.record(["2022-04-15", "2023-04-15", "2024-04-14"], "Yearly Club")
        self.assertEqual(
            {
                item["billing_frequency"]: item["next_expected_payment"]
                for item in self.detect()
            },
            {"weekly": "2024-01-26", "quarterly": "2024-10-31", "yearly": "2025-04-15"},
        )

    def test_irregular_charges_large_changes_credits_and_mixed_currency_do_not_match(
        self,
    ):
        self.record(["2024-01-01", "2024-01-14", "2024-02-26"], "Irregular Store")
        dates = ["2024-01-07", "2024-02-07", "2024-03-07"]
        self.record(dates, "Large Changes", ["-9.99", "-29.99", "-59.99"])
        self.record(dates, "Credit", ["9.99"] * 3)
        for day, currency in zip(dates, ["EUR", "BGN", "USD"]):
            self.record([day], "Mixed Currency", currency=currency)
        self.record(["2024-03-01"] * 3, "Duplicate Same Day")
        self.assertEqual(self.detect(), [])

    def test_missing_or_insufficient_history_returns_an_empty_list(self):
        self.assertEqual(self.detect(), [])
        self.record(["2024-01-15", "2024-02-15"])
        self.assertEqual(self.detect(), [])
        self.assertEqual(self.client.get("/api/subscriptions/").data, [])

    def test_reruns_refresh_candidates_and_preserve_confirmed_edits(self):
        self.record(["2024-01-15", "2024-02-15", "2024-03-15"])
        (original,) = self.detect()
        self.assertEqual(self.detect(), [original])
        self.record(["2024-04-15"])
        (updated,) = self.detect()
        self.assertEqual(updated["id"], original["id"])
        self.assertEqual(updated["next_expected_payment"], "2024-05-15")
        url = f"/api/subscriptions/{original['id']}/"
        confirmed = self.client.patch(
            url,
            {
                "status": "confirmed",
                "merchant": "My provider",
                "estimated_amount": "11.00",
            },
            format="json",
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.record(["2024-05-15"])
        self.assertEqual(self.detect(), [confirmed.data])
        self.assertEqual(Subscription.objects.count(), 1)

    def test_owner_scoping_patch_validation_and_delete(self):
        dates = ["2024-01-15", "2024-02-15", "2024-03-15"]
        self.record(dates, user=self.other)
        self.assertEqual(self.detect(), [])
        self.client.force_authenticate(self.other)
        (other_item,) = self.detect()
        self.client.force_authenticate(self.owner)
        other_url = f"/api/subscriptions/{other_item['id']}/"
        self.assertEqual(self.client.get("/api/subscriptions/").data, [])
        self.assertEqual(
            self.client.patch(other_url, {"status": "confirmed"}).status_code, 404
        )
        self.assertEqual(self.client.delete(other_url).status_code, 404)

        self.record(dates)
        (item,) = self.detect()
        self.assertNotEqual(item["id"], other_item["id"])
        url = f"/api/subscriptions/{item['id']}/"
        bad = self.client.patch(
            url, {"estimated_amount": "-1.00", "status": "fraud"}, format="json"
        )
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(set(bad.data), {"estimated_amount", "status"})
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertEqual(self.client.get("/api/subscriptions/").data, [])
        self.assertTrue(
            Subscription.objects.filter(pk=other_item["id"], owner=self.other).exists()
        )

    def test_anonymous_requests_are_rejected(self):
        self.client.force_authenticate(None)
        for method, url in (
            ("get", "/api/subscriptions/"),
            ("post", "/api/subscriptions/detect/"),
            ("patch", "/api/subscriptions/1/"),
            ("delete", "/api/subscriptions/1/"),
        ):
            self.assertEqual(getattr(self.client, method)(url).status_code, 401)
