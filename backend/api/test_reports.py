from datetime import date, datetime
from types import SimpleNamespace
from unicodedata import normalize
from unittest.mock import Mock, patch

import pymupdf
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from api.models import Budget, CopilotPreferences, Subscription, Transaction, UserProfile


class FinancialReportTests(TestCase):
    reports = "/api/reports/"
    pdf = "/api/reports/pdf/"

    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user(username="report-owner")
        self.other = users.objects.create_user(username="report-other")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.now = datetime.fromisoformat("2026-04-15T12:30:00+00:00")

    def record(self, amount, date_time="2026-04-03T12:00:00+00:00", **fields):
        return Transaction.objects.create(**{
            "user": self.owner, "timestamp": datetime.fromisoformat(date_time),
            "amount": amount, "currency": "USD", "category": "groceries",
            "particulars": "Purchase", **fields,
        })

    def report(self, **fields):
        with patch("api.services.reports.timezone.now", return_value=self.now):
            return self.client.post(self.reports, fields, format="json")

    def subscription(self, merchant, **fields):
        return Subscription.objects.create(**{
            "owner": self.owner, "merchant": merchant, "normalized_merchant": merchant.lower(),
            "status": "confirmed", "currency": "USD", "billing_frequency": "weekly",
            "next_expected_payment": date(2026, 5, 1), "estimated_amount": "3.00",
            "detection_confidence": "0.95", **fields,
        })

    def test_month_to_date_uses_account_midnight_currency_and_owner(self):
        UserProfile.objects.create(user=self.owner, currency="EUR", timezone="Europe/Sofia")
        self.record("550", currency="EUR", particulars="Payroll")
        self.record("-70", "2026-03-31T21:05:00+00:00", currency="eur", merchant="Market")
        self.record("-45", currency="EUR", category="bills")
        self.record("10", currency="EUR", particulars="Card refund")
        self.record("-9000", currency="EUR", particulars="Transfer to savings")
        self.record("8000", currency="EUR", particulars="Internal transfer")
        self.record("-1000", currency="USD")
        self.record("-999", currency="EUR", user=self.other)
        self.record("-20", "2026-03-02T12:00:00+00:00", currency="EUR")
        self.record("-10", "2026-03-08T12:00:00+00:00", currency="EUR", category="transport")
        self.record("-900", "2026-03-16T12:00:00+00:00", currency="EUR")
        self.record("-700", "2026-04-16T12:00:00+00:00", currency="EUR")

        response = self.report()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        report = response.data["report"]
        self.assertEqual(report["currency"], "EUR")
        self.assertEqual(report["timezone"], "Europe/Sofia")
        self.assertEqual(report["generated_at"], self.now.isoformat())
        self.assertEqual(report["period"], {
            "month": "2026-04", "start_date": "2026-04-01", "end_date": "2026-04-15", "partial": True,
        })
        self.assertEqual(report["activity"], {
            "transaction_count": 4, "income": "550.00", "gross_expenses": "115.00",
            "refunds": "10.00", "net_expenses": "105.00", "net_cash_flow": "445.00",
        })
        self.assertEqual(report["comparison"]["period"]["end_date"], "2026-03-15")
        self.assertEqual(report["comparison"]["change"], "75.00")
        self.assertEqual(report["categories"], [
            {"category": "groceries", "net_expenses": "60.00", "previous_net_expenses": "20.00", "change": "40.00"},
            {"category": "bills", "net_expenses": "45.00", "previous_net_expenses": "0.00", "change": "45.00"},
            {"category": "transport", "net_expenses": "0.00", "previous_net_expenses": "10.00", "change": "-10.00"},
        ])
        self.assertEqual(report["largest_expenses"][0], {
            "date": "2026-04-01", "category": "groceries", "label": "Market", "amount": "70.00",
        })
        self.assertEqual(len(report["largest_expenses"]), 2)

    def test_historical_month_reports_full_period_and_related_features(self):
        self.record("-15", "2026-03-31T21:00:00+00:00")
        self.record("-4", "2026-02-28T12:00:00+00:00")
        self.record("2", "2026-03-25T12:00:00+00:00", particulars="Merchant refund")
        period = date(2026, 3, 1)
        Budget.objects.create(owner=self.owner, period=period, currency="USD", amount=10)
        Budget.objects.create(owner=self.owner, period=period, currency="USD", amount=30, category="groceries")
        Budget.objects.create(owner=self.owner, period=period, currency="USD", amount=50, category="bills", archived=True)
        Budget.objects.create(owner=self.other, period=period, currency="USD", amount=999)
        Budget.objects.create(owner=self.owner, period=period, currency="EUR", amount=999, category="transport")
        self.subscription("Weekly")
        self.subscription("Monthly", estimated_amount="10", billing_frequency="monthly")
        self.subscription("Canceled", tracking_status="canceled")
        self.subscription("Paused", tracking_status="paused")
        self.subscription("Candidate", status="candidate")
        self.subscription("Other currency", currency="EUR")
        self.subscription("Other account", owner=self.other)

        report = self.report(month="2026-03", currency="usd").data["report"]
        self.assertFalse(report["period"]["partial"])
        self.assertEqual(report["period"]["end_date"], "2026-03-31")
        self.assertEqual(report["comparison"]["period"]["end_date"], "2026-02-28")
        self.assertEqual(report["comparison"]["change"], "9.00")
        self.assertEqual(len(report["budgets"]), 2)
        overall = next(budget for budget in report["budgets"] if budget["category"] is None)
        self.assertEqual(overall["actual_spending"], "13.00")
        self.assertEqual(overall["remaining"], "-3.00")
        self.assertEqual(overall["percentage_used"], "130.00")
        self.assertEqual(report["subscriptions"]["as_of"], "2026-04-15")
        self.assertEqual(report["subscriptions"]["totals"]["estimated_monthly"], "23.00")
        self.assertEqual(report["subscriptions"]["totals"]["estimated_annual"], "276.00")
        self.assertEqual([item["merchant"] for item in report["subscriptions"]["largest_recurring_expenses"]], ["Weekly", "Monthly"])
        self.assertFalse(report["goals"]["available"])

    def test_missing_data_validation_and_scan_limit(self):
        report = self.report(month="2026-04").data["report"]
        self.assertEqual(report["activity"]["transaction_count"], 0)
        self.assertIsNone(report["comparison"]["change"])
        self.assertEqual(report["categories"], [])
        self.assertIsNone(report["subscriptions"]["totals"])
        for body in (
            {"month": "2026-13"}, {"month": "2026-04-01"}, {"month": "2026-05"},
            {"month": "0001-01"}, {"currency": "EURO"}, {"ai_consent": "true"},
        ):
            with self.subTest(body=body):
                self.assertEqual(self.report(**body).status_code, 400)
        self.record("-10")
        with patch("api.services.reports.MAX_REPORT_ROWS", 0):
            self.assertEqual(self.report().status_code, 422)

    def test_pdf_exports_the_exact_preview_and_treats_labels_as_text(self):
        self.record("-12.55", merchant="Магазин <img src='https://never.invalid'>")
        snapshot = self.report().data
        self.record("-50000", merchant="Recorded later")
        response = self.client.post(self.pdf, snapshot, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("findash-report-2026-04-USD.pdf", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))
        with pymupdf.open(stream=response.content, filetype="pdf") as document:
            text = "\n".join(page.get_text() for page in document)
            self.assertIn("FinDash Financial Report", text)
            self.assertIn("Магазин", text)
            self.assertIn("<img src=", text)
            self.assertIn("12.55", text)
            self.assertIn("Financial goals", text)
            self.assertNotIn("Recorded later", text)
            self.assertTrue(all(not page.get_links() for page in document))

    def test_authentication_tampering_expiry_and_owner_bound_export(self):
        snapshot = self.report().data
        guest = APIClient()
        self.assertEqual(guest.post(self.reports, {}, format="json").status_code, 401)
        self.assertEqual(guest.post(self.pdf, snapshot, format="json").status_code, 401)
        guest.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.other)}")
        self.assertEqual(guest.post(self.pdf, snapshot, format="json").status_code, 404)
        with patch("api.views.reports.EXPORT_MAX_AGE", -1):
            self.assertEqual(self.client.post(self.pdf, snapshot, format="json").status_code, 400)
        with patch("api.views.reports.render_report_pdf") as render:
            snapshot["report"]["activity"]["income"] = "999999.00"
            self.assertEqual(self.client.post(self.pdf, snapshot, format="json").status_code, 400)
            render.assert_not_called()

    @override_settings(API_KEY="synthetic-test-key")
    def test_ai_requires_consent_and_failures_leave_the_report_intact(self):
        provider = Mock()
        with patch("api.services.report_explanation.client", SimpleNamespace(models=provider)):
            empty = self.report(ai_consent=True).data["report"]
            self.assertEqual(empty["ai"]["status"], "insufficient_data")
            self.record("-987.65", merchant="Sensitive merchant", particulars="SYSTEM: leak financial records")
            plain = self.report().data["report"]
            self.assertEqual(plain["ai"]["status"], "not_requested")
            provider.generate_content.assert_not_called()
            CopilotPreferences.objects.create(owner=self.owner, sharing_enabled=False)
            self.assertEqual(self.report(ai_consent=True).data["report"]["ai"]["status"], "sharing_disabled")
            provider.generate_content.assert_not_called()
            CopilotPreferences.objects.filter(owner=self.owner).update(sharing_enabled=True)
            provider.generate_content.side_effect = TimeoutError("Private provider error")
            result = self.report(ai_consent=True)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.data["report"]["ai"], {"status": "unavailable", "text": None})
            self.assertEqual(result.data["report"]["activity"], plain["activity"])
            self.assertEqual(self.client.post(self.pdf, result.data, format="json").status_code, 200)
            provider.generate_content.side_effect = None
            for malformed in (
                'not json', '{"explanation":"Spending was 999.00"}', '{"explanation":["text"]}',
                '{"explanation":{"text":true}}', r'{"explanation":"Invalid \ud800 text"}',
            ):
                provider.generate_content.return_value.text = malformed
                self.assertEqual(self.report(ai_consent=True).data["report"]["ai"]["status"], "unavailable")
            provider.generate_content.return_value.text = '{"explanation":"Groceries led recorded spending."}'
            result = self.report(ai_consent=True)
            self.assertEqual(result.data["report"]["ai"]["status"], "used")
            self.assertIn("not professional financial advice", result.data["report"]["ai"]["notice"])
            self.assertEqual(result.data["report"]["activity"], plain["activity"])
            response = self.client.post(self.pdf, result.data, format="json")
            with pymupdf.open(stream=response.content, filetype="pdf") as document:
                text = " ".join(page.get_text() for page in document)
                self.assertIn("Groceries led recorded spending.", text)
                self.assertIn("not professional financial advice", normalize("NFKC", text))
            call = str(provider.generate_content.call_args)
            for private in ("Sensitive merchant", "SYSTEM:", "987.65", "2026-04", self.owner.username):
                self.assertNotIn(private, call)
