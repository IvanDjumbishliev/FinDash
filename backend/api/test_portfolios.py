from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import requests
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import DatabaseError, close_old_connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import Portfolio, Stock, Transaction, VirtualTrade
from api.services.portfolio_quotes import market_quote
from api.services.virtual_portfolios import InvalidTrade, record_trade


class VirtualPortfolioTests(TestCase):
    url = "/api/portfolios/"

    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user(username="portfolio-owner")
        self.other = users.objects.create_user(username="portfolio-other")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.foreign = Portfolio.objects.create(owner=self.other, name="Other account")
        self.portfolio = Portfolio.objects.create(owner=self.owner, name="Paper trading")
        self.now = timezone.now()
        cache.clear()
        self.addCleanup(cache.clear)

    def trade(self, side="buy", *, portfolio=None, **fields):
        portfolio = portfolio or self.portfolio
        return self.client.post(f"{self.url}{portfolio.pk}/trades/", {
            "side": side, "ticker": "aapl", "quantity": "10", "price": "100", **fields,
        }, format="json")

    def get(self, resource, portfolio=None):
        return self.client.get(f"{self.url}{(portfolio or self.portfolio).pk}/{resource}/")

    def market_data(self, currency="USD", price=160, timestamp=None, symbol="AAPL"):
        return {"chart": {"result": [{"meta": {
            "regularMarketPrice": price, "currency": currency,
            "regularMarketTime": int((timestamp or self.now).timestamp()), "symbol": symbol,
        }}]}}

    def test_fifo_includes_fees_and_prices_holdings_separately_from_virtual_execution(self):
        with patch("api.services.portfolio_quotes._finance_data", return_value=self.market_data()) as provider:
            buy = self.trade(fees="10")
            self.assertEqual(buy.status_code, 201)
            self.assertEqual(buy.data["ticker"], "AAPL")
            self.assertEqual(buy.data["price"], "100.00000000")
            self.assertTrue(buy.data["is_virtual"])
            self.assertTrue(buy.data["timestamp"])
            self.assertEqual(self.trade(quantity="5", price="120", fees="5").status_code, 201)
            self.assertEqual(self.trade("sell", quantity="12", price="150", fees="6").status_code, 201)
            provider.assert_not_called()

            holdings = self.get("holdings").data
            self.assertEqual(holdings["cost_basis_method"], "FIFO")
            position = holdings["holdings"][0]
            self.assertEqual(position["quantity"], "3")
            self.assertEqual(position["cost_basis"], "363")
            self.assertEqual(position["average_cost_per_share"], "121")
            self.assertEqual(position["realized_pnl"], "542")
            self.assertEqual(position["market_quote"]["price"], "160")
            self.assertEqual(position["market_value"], "480")
            self.assertEqual(position["unrealized_pnl"], "117")
            report = self.get("performance").data["performance"]
            self.assertEqual(report["realized_pnl"], "542")
            self.assertEqual(report["total_pnl"], "659")
            self.assertEqual(report["fees"], "21")
            provider.assert_called_once_with("/v8/finance/chart/AAPL", range="5d", interval="1d")

            self.assertEqual(self.trade("sell", quantity="3", price="140", fees="2").status_code, 201)
            report = self.get("performance").data
            self.assertEqual(report["performance"]["realized_pnl"], "597")
            self.assertEqual(report["performance"]["unrealized_pnl"], "0")
            self.assertEqual(report["by_ticker"][0]["quantity"], "0")
            self.assertEqual(self.get("holdings").data["holdings"], [])

    def test_fractional_lots_preserve_basis_across_partial_sales(self):
        self.assertEqual(self.trade(quantity="1.5", price="0.20", fees="0.10").status_code, 201)
        for _ in range(3):
            self.assertEqual(self.trade("sell", quantity="0.5", price="0.26").status_code, 201)
        report = self.get("performance").data["performance"]
        self.assertEqual(report["open_cost_basis"], "0")
        self.assertEqual(report["realized_pnl"], "-0.01")

    def test_invalid_trades_and_oversells_leave_the_ledger_unchanged(self):
        for fields in (
            {"ticker": "../AAPL"}, {"ticker": "A."}, {"ticker": "%AAPL"}, {"side": " short "},
            {"quantity": "0"}, {"quantity": "-1"}, {"quantity": "1.000000001"},
            {"price": "0"}, {"price": "NaN"}, {"fees": "-1"}, {"currency": "EUR"},
        ):
            with self.subTest(fields=fields):
                self.assertEqual(self.trade(**fields).status_code, 400)
        self.assertEqual(self.trade("sell", quantity="0.01").status_code, 400)
        self.assertEqual(VirtualTrade.objects.count(), 0)
        self.portfolio.refresh_from_db()
        self.assertEqual(self.portfolio.ledger_version, 0)
        self.assertEqual(self.trade(quantity="0.015").status_code, 201)
        self.assertEqual(self.trade("sell", quantity="0.01500001").status_code, 400)
        self.assertEqual(self.trade("sell", quantity="0.015", ticker="MSFT").status_code, 400)
        self.assertEqual(VirtualTrade.objects.count(), 1)

    def test_client_order_id_allows_retry_without_duplicate_or_different_terms(self):
        key = str(uuid4())
        first = self.trade(client_order_id=key)
        self.assertEqual(first.status_code, 201)
        again = self.trade(client_order_id=key, currency="usd")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.data, first.data)
        self.assertEqual(self.trade(client_order_id=key, quantity="12").status_code, 409)
        self.portfolio.refresh_from_db()
        self.assertEqual(self.portfolio.ledger_version, 1)
        self.assertEqual(VirtualTrade.objects.count(), 1)

    def test_endpoints_are_authenticated_and_owner_scoped(self):
        guest = APIClient()
        self.assertEqual(guest.get(self.url).status_code, 401)
        self.assertEqual(guest.post(self.url, {"name": "Guest"}, format="json").status_code, 401)
        self.assertEqual(self.get("holdings", self.foreign).status_code, 404)
        self.assertEqual(self.get("performance", self.foreign).status_code, 404)
        self.assertEqual(self.trade(portfolio=self.foreign).status_code, 404)
        self.assertEqual([item["id"] for item in self.client.get(self.url).data], [self.portfolio.pk])
        result = self.client.post(self.url, {"name": "Second", "currency": "eur", "owner": self.other.pk,
                                              "is_virtual": False}, format="json")
        self.assertEqual(result.status_code, 201)
        self.assertTrue(result.data["is_virtual"])
        self.assertEqual(result.data["currency"], "EUR")
        self.assertEqual(Portfolio.objects.get(pk=result.data["id"]).owner, self.owner)
        self.assertEqual(Stock.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_provider_outages_and_currency_mismatch_preserve_unknown_values(self):
        self.trade(ticker="AAPL")
        self.trade(ticker="MSFT")
        self.trade(ticker="GOOG")

        def finance(path, **kwargs):
            if path.endswith("AAPL"):
                return self.market_data()
            if path.endswith("MSFT"):
                return self.market_data(currency="EUR", symbol="MSFT")
            raise requests.Timeout("offline")

        with patch("api.services.portfolio_quotes._finance_data", side_effect=finance):
            holdings = self.get("holdings").data["holdings"]
            by_ticker = {item["ticker"]: item for item in holdings}
            self.assertEqual(by_ticker["MSFT"]["market_quote"]["status"], "currency_mismatch")
            self.assertIsNone(by_ticker["MSFT"]["unrealized_pnl"])
            self.assertEqual(by_ticker["GOOG"]["market_quote"]["status"], "unavailable")
            self.assertIsNone(by_ticker["GOOG"]["market_value"])
            report = self.get("performance").data["performance"]
            self.assertFalse(report["valuation_complete"])
            self.assertEqual(report["priced_market_value"], "1600")
            self.assertEqual(report["realized_pnl"], "0")
            self.assertIsNone(report["market_value"])
            self.assertIsNone(report["unrealized_pnl"])
            self.assertIsNone(report["total_pnl"])

    def test_market_quotes_keep_provider_currency_case_and_reject_stale_or_invalid_metadata(self):
        results = [
            self.market_data(currency="GBp", symbol="VOD.L"),
            self.market_data(timestamp=self.now - timedelta(days=8), symbol="MSFT"),
            self.market_data(price="NaN", symbol="GOOG"),
        ]
        with patch("api.services.portfolio_quotes._finance_data", side_effect=results):
            self.assertEqual(market_quote("VOD.L")["currency"], "GBp")
            self.assertEqual(market_quote("MSFT")["status"], "stale")
            self.assertEqual(market_quote("GOOG")["status"], "unavailable")

    def test_database_errors_roll_back_the_version_and_virtual_trade(self):
        with patch("api.services.virtual_portfolios.VirtualTrade.objects.create", side_effect=DatabaseError):
            self.assertEqual(self.trade().status_code, 503)
        self.portfolio.refresh_from_db()
        self.assertEqual(self.portfolio.ledger_version, 0)
        self.assertFalse(self.portfolio.trades.exists())


class ConcurrentVirtualTradeTests(TransactionTestCase):
    def test_two_concurrent_sales_cannot_oversell(self):
        owner = get_user_model().objects.create_user(username="concurrent-trader")
        portfolio = Portfolio.objects.create(owner=owner, name="Paper")
        terms = {"ticker": "AAPL", "quantity": Decimal("1"), "price": Decimal("50"), "fees": Decimal(0)}
        record_trade(owner, portfolio.pk, side="buy", **terms)
        barrier = Barrier(2)

        def sell():
            close_old_connections()
            try:
                barrier.wait(timeout=3)
                record_trade(owner, portfolio.pk, side="sell", **terms)
                return "sold"
            except InvalidTrade:
                return "insufficient"
            except DatabaseError:
                return "busy"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: sell(), range(2)))
        self.assertEqual(outcomes.count("sold"), 1)
        self.assertIn(next(item for item in outcomes if item != "sold"), {"insufficient", "busy"})
        with self.assertRaises(InvalidTrade):
            record_trade(owner, portfolio.pk, side="sell", **terms)
        self.assertEqual(portfolio.trades.count(), 2)
