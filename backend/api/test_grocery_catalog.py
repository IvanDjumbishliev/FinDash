import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from html import escape
from io import StringIO
from unittest.mock import Mock, patch

from requests import Timeout

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from api.models import GroceryCatalogRefresh, GroceryOffer, GroceryRetailer
from api.services.grocery_catalog import ADAPTERS, normalize_offer, parse_package, refresh_catalog
from api.views.deals import lidl_product_offers, scrape_kaufland


class GroceryCatalogTests(TestCase):
    now = datetime(2026, 11, 21, 12, tzinfo=UTC)

    def row(self, **overrides):
        return {"name": "Краве масло 250 г", "image_url": "https://www.lidl.bg/image.jpg",
                "_catalog": {
                    "source_url": "https://www.lidl.bg/offers", "product_id": "product-1",
                    "start": "2026-11-20", "end": "2026-11-24", "price_text": "2,99 €", **overrides,
                }}

    def test_normalizes_units_and_ambiguous_weights(self):
        for text, quantity, unit, count in (
            ("250 г", ".25", "kg", 1), ("0,25 кг", ".25", "kg", 1),
            ("2 × 250 г", ".5", "kg", 2), ("250g x 2", ".5", "kg", 2),
            ("500 мл", ".5", "l", 1), ("1.5 L", "1.5", "l", 1),
            ("6 бр.", "6", "item", 1),
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_package(text)[:3], (Decimal(quantity), unit, count))
        for text in ("от 500 г", "200–300 г", "200/300 г", "250 г / 500 г", "за 1 кг", "1,5 бр.", "0 г"):
            with self.subTest(text=text):
                self.assertIsNone(parse_package(text))

    def test_preserves_gaps_and_does_not_infer_currency_or_price(self):
        offer = normalize_offer(self.row(), self.now)
        self.assertEqual(offer["normalized_name"], "краве масло")
        self.assertEqual(offer["price"], Decimal("2.99"))
        self.assertEqual(offer["unit_price"], Decimal("11.960000"))
        self.assertEqual(offer["retailer_product_id"], "product-1")

        for metadata in ({"price_text": "2,99 € / 5,85 лв."}, {"price_text": ""},
                         {"price_text": "", "amount": "invalid"}):
            result = normalize_offer(self.row(**metadata), self.now)
            self.assertIsNone(result["price"])
            self.assertIsNone(result["unit_price"])
        unknown_currency = normalize_offer(self.row(price_text="", amount=2.99, currency=None), self.now)
        self.assertEqual(unknown_currency["price"], Decimal("2.99"))
        self.assertIsNone(unknown_currency["currency"])
        self.assertIsNone(unknown_currency["unit_price"])
        brochure = normalize_offer(
            {**self.row(start=None, end=None, product_id=None), "image_url": "data:image/jpeg;base64,AA=="},
            self.now,
        )
        self.assertEqual(brochure["image_url"], "")
        self.assertIsNone(brochure["expires_on"])
        self.assertEqual(brochure["availability_status"], "advertised")

    def test_repeat_imports_update_existing_offers_and_preserve_pack_sizes(self):
        adapter = Mock(return_value=[
            self.row(), self.row(),
            self.row(quantity_text="500 г", name="Краве масло 500 г"),
            self.row(quantity_text="2 × 250 г", name="Краве масло 2 × 250 г"),
        ])
        with patch.dict(ADAPTERS, {GroceryRetailer.LIDL: adapter}):
            self.assertEqual(refresh_catalog(GroceryRetailer.LIDL, now=self.now), ("success", 3))
            self.assertEqual(refresh_catalog(GroceryRetailer.LIDL, now=self.now + timedelta(minutes=15)), ("skipped", 3))
            adapter.assert_called_once_with(catalog=True)
            adapter.return_value = [self.row(price_text="2,49 €")]
            later = self.now + timedelta(hours=2)
            self.assertEqual(refresh_catalog(GroceryRetailer.LIDL, now=later), ("success", 1))
        self.assertEqual(GroceryOffer.objects.count(), 3)
        self.assertEqual(GroceryOffer.objects.get(quantity=Decimal(".25")).price, Decimal("2.49"))
        self.assertEqual(set(GroceryOffer.objects.filter(quantity=".5").values_list("pack_count", flat=True)), {1, 2})
        self.assertEqual(GroceryOffer.objects.comparable(now=later).count(), 1)

    def test_expired_undated_stale_and_membership_offers_are_not_comparable(self):
        rows = [
            self.row(),
            self.row(product_id="expired", end="2026-11-20"),
            self.row(product_id="expired-instant", end=(self.now - timedelta(minutes=15)).timestamp()),
            self.row(product_id="undated", start=None, end=None),
            self.row(product_id="membership", membership=True),
            self.row(product_id="future", start="2026-11-22"),
            self.row(product_id="unknown-price", price_text=""),
        ]
        with patch.dict(ADAPTERS, {GroceryRetailer.LIDL: Mock(return_value=rows)}):
            refresh_catalog(GroceryRetailer.LIDL, now=self.now)
        self.assertEqual(list(GroceryOffer.objects.comparable(now=self.now).values_list("retailer_product_id", flat=True)), ["product-1"])
        self.assertEqual(GroceryOffer.objects.current(now=self.now).count(), 2)
        self.assertFalse(GroceryOffer.objects.current(now=self.now + timedelta(hours=49)).exists())

    def test_outage_leaves_existing_offers_and_freshness_intact(self):
        adapter = Mock(side_effect=[[self.row()], Timeout("source outage")])
        with patch.dict(ADAPTERS, {GroceryRetailer.LIDL: adapter}):
            refresh_catalog(GroceryRetailer.LIDL, now=self.now)
            later = self.now + timedelta(hours=2)
            self.assertEqual(refresh_catalog(GroceryRetailer.LIDL, now=later), ("unavailable", 1))
        state = GroceryCatalogRefresh.objects.get(retailer=GroceryRetailer.LIDL)
        self.assertEqual(state.last_success_at, self.now)
        self.assertEqual(state.last_attempt_at, later)
        self.assertEqual(GroceryOffer.objects.get().last_successful_update, self.now)
        self.assertEqual(GroceryOffer.objects.comparable(now=later).count(), 1)

    @override_settings(GROCERY_CATALOG_RETAILERS=frozenset({"lidl"}))
    def test_command_only_runs_explicitly_enabled_adapters(self):
        with patch("api.management.commands.refresh_grocery_catalog.refresh_catalog", return_value=("success", 1)) as refresh:
            with self.assertRaises(CommandError):
                call_command("refresh_grocery_catalog", "lidl", "fantastico")
            refresh.assert_not_called()
            call_command("refresh_grocery_catalog", "lidl", stdout=StringIO())
            refresh.assert_called_once_with("lidl")

    @patch("api.views.deals.requests.get")
    def test_structured_metadata_is_available_without_changing_public_shape(self, get):
        stamp = self.now.timestamp()
        item = {"fullTitle": "Milk", "productId": 123, "grammage": "500 мл",
                "storeStartDate": stamp - 3600, "storeEndDate": stamp + 3600,
                "price": {"price": 1.25, "displayedCurrency": "€"}}
        html = f'<div data-grid-data="{escape(json.dumps(item), quote=True)}"></div>'
        offers = lidl_product_offers(html, stamp, catalog=True)
        self.assertEqual(offers[0]["_catalog"]["product_id"], 123)
        self.assertEqual(normalize_offer(offers[0], self.now)["quantity"], Decimal(".5"))
        self.assertEqual(lidl_product_offers(html, stamp), [])

        row = {"offerId": "offer-1", "productId": "product-2", "title": "Milk", "unit": "1 l",
               "formattedPrice": "2,20 лв.", "brand": "Example", "dateFrom": "2020-11-01", "dateTo": "2099-12-01"}
        payload = {"props": {"offerData": {"cycles": [{"categories": [{"name": "Dairy", "offers": [row]}]}]}}}
        get.return_value = Mock(text=f'window.SSR["test"] = {json.dumps(payload)};')
        offer = normalize_offer(scrape_kaufland(catalog=True)[0], self.now)
        self.assertEqual(offer["retailer_offer_id"], "offer-1")
        self.assertEqual(offer["retailer_product_id"], "product-2")
        self.assertEqual(offer["brand"], "Example")
        self.assertEqual(offer["category"], "Dairy")
        self.assertEqual(offer["currency"], "BGN")
