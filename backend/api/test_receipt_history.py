from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.db.models import Sum
from rest_framework.test import APIClient

from api.models import Receipt, ReceiptItem, Transaction
from api.services.receipts import SOFIA
from api.services.statements.intelligence import merchant_identity


class ReceiptHistoryTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user(username="history-owner")
        self.other = users.create_user(username="history-other")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.purchased_at = datetime(2026, 11, 21, 0, 30, tzinfo=SOFIA)
        self.receipt = self.create_receipt(self.owner, "one")
        self.foreign = self.create_receipt(self.other, "two", merchant="Other Market")
        self.url = f"/api/receipts/{self.receipt.pk}/"

    def create_receipt(self, owner, fingerprint, *, merchant="Sample Market", currency="EUR", total="12.00"):
        receipt = Receipt.objects.create(
            owner=owner, merchant=merchant, normalized_merchant=merchant_identity(merchant)[1],
            purchased_at=self.purchased_at, currency=currency, total=total, source="upload",
            image_digest=fingerprint, fingerprint=fingerprint,
        )
        ReceiptItem.objects.create(receipt=receipt, original_description="Кис. мл.", normalized_name="кисело мляко",
                                   category="dairy", line_total=total)
        return receipt

    def payment(self, *, owner=None, days=0, amount="-12.00", currency="EUR", merchant="Sample Market"):
        return Transaction.objects.create(
            user=owner or self.owner, timestamp=self.purchased_at + timedelta(days=days),
            amount=amount, currency=currency, category="groceries", merchant=merchant, particulars=merchant,
        )

    def statistics(self, **params):
        response = self.client.get("/api/receipts/statistics/", params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def test_search_by_store_normalized_product_and_sofia_calendar_date(self):
        response = self.client.get("/api/receipts/", {
            "store": "sample", "product": "Кис. мл.", "start": "2026-11-21", "end": "2026-11-21",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.data["results"]], [str(self.receipt.pk)])
        self.assertEqual(self.client.get("/api/receipts/", {"end": "2026-11-20"}).data["count"], 0)
        self.assertEqual(self.client.get("/api/receipts/", {"start": "2026-11-22", "end": "2026-11-21"}).status_code, 400)
        self.assertEqual(self.statistics(store="Other"), [])

    def test_rank_suggestions_require_a_link_and_never_duplicate_bank_spending(self):
        same = self.payment()
        posted = self.payment(days=2, merchant="Other name")
        wrong_currency = self.payment(currency="BGN")
        foreign = self.payment(owner=self.other)
        self.payment(days=4)
        self.payment(amount="-12.01")
        matches = self.client.get(self.url + "reconciliation/").data
        self.assertEqual([entry["id"] for entry in matches], [same.pk, posted.pk])
        self.assertEqual([entry["confidence"] for entry in matches], ["high", "review"])
        self.receipt.refresh_from_db()
        self.assertIsNone(self.receipt.transaction_id)
        self.assertEqual(self.client.patch(self.url + "reconciliation/", {"transaction": wrong_currency.pk}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(self.url + "reconciliation/", {"transaction": foreign.pk}, format="json").status_code, 404)

        def ledger_spending():
            return Transaction.objects.filter(user=self.owner, currency="EUR").aggregate(total=Sum("amount"))["total"]

        before = ledger_spending()
        url = "/api/analytics/spending-heatmap/"
        params = {"start": "2026-11-20", "end": "2026-11-25", "currency": "EUR"}
        heatmap = self.client.get(url, params)
        self.assertEqual(heatmap.status_code, 200)
        self.assertEqual(self.client.patch(self.url + "reconciliation/", {"transaction": same.pk}, format="json").status_code, 200)
        summary = self.statistics()[0]
        self.assertEqual(summary["total"], "12.00")
        self.assertEqual(summary["item_total"], "12.00")
        self.assertEqual(summary["linked_count"], 1)
        self.assertEqual(summary["receipt_count"], 1)
        self.assertEqual(ledger_spending(), before)
        self.assertEqual(self.client.get(url, params).data, heatmap.data)
        another = self.create_receipt(self.owner, "three")
        self.assertNotIn(same.pk, [entry["id"] for entry in self.client.get(
            f"/api/receipts/{another.pk}/reconciliation/",
        ).data])

    def test_corrections_refresh_statistics_and_discard_incompatible_links(self):
        payment = self.payment()
        self.client.patch(self.url + "reconciliation/", {"transaction": payment.pk}, format="json")
        correction = self.client.patch(self.url, {"total": "9.00", "items": [
            {"original_description": "Bread", "category": "bakery", "quantity": "1", "unit": "item", "line_total": "10.00"},
            {"original_description": "Bread", "category": "bakery", "line_total": "-1.00"},
        ]}, format="json")
        self.assertEqual(correction.status_code, 200, correction.data)
        self.assertIsNone(correction.data["transaction"])
        self.assertEqual([item["normalized_name"] for item in correction.data["items"]], ["bread", "bread"])
        stats = self.statistics(product="Bread")[0]
        self.assertEqual(stats["item_total"], "9.00")
        self.assertEqual(stats["categories"], [{"name": "bakery", "total": "9.00", "line_count": 2}])
        self.assertEqual(stats["products"], [{"name": "bread", "total": "9.00", "line_count": 2}])
        self.assertEqual(self.statistics(product="кисело мляко"), [])
        self.assertEqual(self.client.patch(self.url, {"items": []}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(self.url, {"items": [{"line_total": "1.00"}]}, format="json").status_code, 400)
        self.assertEqual(self.receipt.items.count(), 2)
        payment.refresh_from_db()
        self.assertEqual(payment.amount, Decimal("-12.00"))

    def test_delete_removes_receipt_items_only_and_other_user_cannot_modify_or_view(self):
        foreign_url = f"/api/receipts/{self.foreign.pk}/"
        self.assertEqual(self.client.get(foreign_url).status_code, 404)
        self.assertEqual(self.client.get(foreign_url + "reconciliation/").status_code, 404)
        self.assertEqual(self.client.patch(foreign_url, {"merchant": "Override"}, format="json").status_code, 404)
        self.assertEqual(self.client.delete(foreign_url).status_code, 404)
        payment = self.payment()
        self.client.patch(self.url + "reconciliation/", {"transaction": payment.pk}, format="json")
        self.assertEqual(self.client.delete(self.url).status_code, 204)
        self.assertFalse(ReceiptItem.objects.filter(receipt_id=self.receipt.pk).exists())
        self.assertTrue(Transaction.objects.filter(pk=payment.pk).exists())
        self.assertEqual(self.statistics(), [])
        self.assertTrue(Receipt.objects.filter(pk=self.foreign.pk).exists())

    def test_statistics_keep_currencies_and_signed_refunds_separate(self):
        self.create_receipt(self.owner, "refund", currency="BGN", total="-3.00")
        bgn, eur = self.statistics()
        self.assertEqual((bgn["currency"], bgn["item_total"]), ("BGN", "-3.00"))
        self.assertEqual((eur["currency"], eur["item_total"]), ("EUR", "12.00"))
