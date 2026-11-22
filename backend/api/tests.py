import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework_simplejwt.tokens import AccessToken
import requests
import pymupdf

from api.models import Stock, Transaction


class DealEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        cache.clear()

    def test_legacy_store_endpoints_keep_compatible_shape(self):
        offer = {"name": "Мляко", "price": "2.50 €", "discount_percent": 25}
        with patch.dict("api.views.legacy_deals.RETAILERS", {"lidl": lambda: [offer], "kaufland": lambda: []}):
            result = self.client.get("/api/leaflet/lidl/")
            self.assertEqual(result.data["response"], [{"info": "Мляко - 2.50 €", "discount": 25, "supermarket": "lidl"}])
            self.assertEqual(self.client.get("/api/leaflet/kaufland/").data["response"], [])

    def test_billa_endpoint_reports_unavailable_without_error(self):
        response = self.client.get("/api/leaflet/billa/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["response"], [])
        self.assertFalse(response.data["available"])

    def test_legacy_search_only_uses_retailer_offers(self):
        with patch.dict("api.views.legacy_deals.RETAILERS", {
            "lidl": lambda: [{"name": "Whole milk", "price": "2.00 €"}],
            "kaufland": lambda: [{"name": "Coffee", "price": "5.00 €"}],
        }):
            response = self.client.post("/api/leaflet/user/", {"prompt": "Milk"}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["response"], [{"info": "Whole milk - 2.00 €", "discount": 0, "supermarket": "lidl"}])
        for invalid in ("", "!" * 10, "milk" * 100):
            self.assertEqual(self.client.post("/api/leaflet/user/", {"prompt": invalid}, format="json").status_code, 400)


class AIEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="ai-test-user", password="test")
        self.client.force_authenticate(user=self.user)
        cache.clear()

    @override_settings(API_KEY="")
    def test_chat_returns_503_when_api_key_is_empty(self):
        response = self.client.post(
            "/api/chat/", {"prompt": "Summarize my spending"}, format="json"
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.data,
            {"code": "not_configured", "error": "AI features are not configured. Add API_KEY to backend/.env"},
        )

    @override_settings(API_KEY=None)
    def test_summary_is_available_without_api_key(self):
        response = self.client.get("/api/summary/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    @override_settings(API_KEY="test-key")
    def test_lazy_client_uses_supported_google_genai_sdk(self):
        from api.views.client import LazyGenAIClient

        fake_sdk_client = SimpleNamespace(models=object())
        with patch(
            "api.views.client.genai.Client", return_value=fake_sdk_client
        ) as client_factory:
            lazy_client = LazyGenAIClient()
            self.assertIs(lazy_client.models, fake_sdk_client.models)

        client_factory.assert_called_once_with(api_key="test-key")


class ScrapedDealsEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        cache.clear()

    def test_lidl_endpoint_returns_list_without_api_key(self):
        with patch(
            "api.views.deals.scrape_lidl",
            return_value=[
                {
                    "name": "Milk",
                    "price": "2.49 €",
                    "image_url": "https://example.com/milk.jpg",
                    "store": "Lidl",
                }
            ],
        ):
            response = self.client.get("/api/deals/lidl/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]["name"], "Milk")
        self.assertEqual(response.data[0]["store"], "Lidl")

    def test_kaufland_endpoint_returns_list_without_api_key(self):
        with patch(
            "api.views.deals.scrape_kaufland",
            return_value=[
                {
                    "name": "Bread",
                    "price": "1.20 €",
                    "image_url": "https://example.com/bread.jpg",
                    "store": "Kaufland",
                }
            ],
        ):
            response = self.client.get("/api/deals/kaufland/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]["name"], "Bread")
        self.assertEqual(response.data[0]["store"], "Kaufland")

    def test_fantastico_endpoint_returns_real_brochure_cards(self):
        with patch(
            "api.views.deals.scrape_fantastico",
            return_value=[
                {
                    "name": "Fantastico brochure 19.11.2026 - 25.11.2026",
                    "price": "19.11.2026 - 25.11.2026",
                    "image_url": "https://example.com/brochure.jpg",
                    "store": "Fantastico",
                }
            ],
        ):
            response = self.client.get("/api/deals/fantastico/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]["store"], "Fantastico")

    def test_scrape_failure_returns_empty_list(self):
        with patch(
            "api.views.deals.requests.get",
            side_effect=RuntimeError("network unavailable"),
        ):
            response = self.client.get("/api/deals/lidl/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])


class StockEndpointTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user(username="stock-user", password="test")
        self.other_user = User.objects.create_user(
            username="other-stock-user", password="test"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    @patch("api.views.stocks._finance_data")
    def test_search_matches_company_names_and_prioritizes_exact_tickers(self, finance):
        finance.return_value = {
            "quotes": [
                {"symbol": "APC.DE", "shortname": "Apple", "quoteType": "EQUITY"},
                {"symbol": "AAPL", "longname": "Apple Inc.", "quoteType": "EQUITY"},
                {"symbol": "AAPL-USD", "shortname": "Apple Coin", "quoteType": "CRYPTO"},
            ],
        }
        response = self.client.get("/api/stocks/search/", {"query": "Apple"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([stock["symbol"] for stock in response.data], ["APC.DE", "AAPL"])
        finance.assert_called_once_with(
            "/v1/finance/search", q="Apple", quotesCount=12, newsCount=0
        )

        response = self.client.get("/api/stocks/search/", {"query": "aapl"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]["symbol"], "AAPL")

    @patch("api.views.stocks._finance_data", return_value={"quotes": []})
    def test_search_returns_clean_error_for_missing_ticker_data(self, finance):
        response = self.client.get("/api/stocks/search/", {"query": "INVALID"})
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.data)

    @patch("api.views.stocks._finance_data", side_effect=requests.ConnectionError("offline"))
    def test_search_returns_clean_error_for_provider_failure(self, finance):
        response = self.client.get("/api/stocks/search/", {"query": "AAPL"})
        self.assertEqual(response.status_code, 502)
        self.assertIn("error", response.data)

    @patch("api.views.stocks._finance_data")
    def test_adding_stock_uses_search_metadata_and_persists_for_current_user(self, finance):
        finance.return_value = {
            "quotes": [{"symbol": "AAPL", "shortname": "Apple Inc.", "quoteType": "EQUITY"}]
        }
        self.client.get("/api/stocks/search/", {"query": "Apple"})
        for _ in range(2):
            response = self.client.post(
                "/api/stocks/watchlist/", {"symbol": " aapl "}, format="json"
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["symbols"], ["AAPL"])

        self.assertEqual(finance.call_count, 1)
        self.assertTrue(Stock.objects.filter(user=self.user, ticker="AAPL", name="Apple Inc.").exists())
        self.assertFalse(Stock.objects.filter(user=self.other_user).exists())

    @patch("api.views.stocks._finance_data", return_value={"quotes": []})
    def test_invalid_ticker_is_not_saved(self, finance):
        response = self.client.post("/api/stocks/watchlist/", {"symbol": "INVALID"}, format="json")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Stock.objects.filter(user=self.user).exists())

    def test_watchlist_returns_one_month_history_for_current_user_only(self):
        Stock.objects.create(
            user=self.user,
            ticker="AAPL",
            name="Apple Inc.",
            quantity=0,
            price_per_share=0,
        )
        Stock.objects.create(
            user=self.other_user,
            ticker="MSFT",
            name="Microsoft",
            quantity=0,
            price_per_share=0,
        )
        history = {"chart": {"result": [{
            "meta": {"exchangeTimezoneName": "America/New_York"},
            "timestamp": [
                int(datetime(2026, 11, day, 1, tzinfo=timezone.utc).timestamp())
                for day in (18, 19, 20)
            ],
            "indicators": {"quote": [{"close": [190.25, 191.5, None]}]},
        }]}}
        with patch("api.views.stocks._finance_data", return_value=history) as finance:
            response = self.client.get("/api/stocks/watchlist/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["symbol"] for item in response.data["stocks"]], ["AAPL"])
        self.assertEqual(
            response.data["stocks"][0]["history"],
            [
                {"date": "2026-11-17", "price": 190.25},
                {"date": "2026-11-18", "price": 191.5},
            ],
        )
        finance.assert_called_once_with(
            "/v8/finance/chart/AAPL", range="1mo", interval="1d"
        )

    def test_watchlist_exposes_timestamped_quote_and_ranges_from_the_same_request(self):
        from django.utils import timezone as django_timezone

        now = django_timezone.now().replace(microsecond=0)
        Stock.objects.create(user=self.user, ticker="LSE.L", name="Example PLC", quantity=0, price_per_share=0)
        meta = {
            "symbol": "LSE.L", "fullExchangeName": "London", "currency": "GBp",
            "regularMarketPrice": 120.5, "regularMarketTime": int(now.timestamp()),
            "regularMarketDayLow": 118, "regularMarketDayHigh": 125,
            "fiftyTwoWeekLow": 90, "fiftyTwoWeekHigh": 160, "regularMarketVolume": 0,
        }
        chart = {"chart": {"result": [{"meta": meta}]}}
        with patch("api.views.stocks._finance_data", return_value=chart) as finance:
            response = self.client.get("/api/stocks/watchlist/")
            self.client.get("/api/stocks/watchlist/")
        finance.assert_called_once()
        self.assertEqual(response.data["stocks"][0]["market"], {
            "price": 120.5, "currency": "GBp", "exchange": "London", "quoted_at": now.isoformat(),
            "day_low": 118, "day_high": 125, "year_low": 90, "year_high": 160, "volume": 0,
        })

    def test_saved_stocks_load_without_provider_and_details_only_use_owned_symbols(self):
        for owner, ticker in ((self.user, "AAPL"), (self.other_user, "MSFT")):
            Stock.objects.create(user=owner, ticker=ticker, name=ticker, quantity=0, price_per_share=0)
        with patch("api.views.stocks._finance_data", return_value={"chart": {"result": [{"meta": None}]}}) as finance:
            saved = self.client.get("/api/stocks/watchlist/", {"include_history": "false"})
            self.assertEqual(saved.data, {"stocks": [{"name": "AAPL", "symbol": "AAPL"}]})
            finance.assert_not_called()
            details = self.client.get("/api/stocks/watchlist/", {"symbol": ["AAPL", "MSFT"]})
            self.assertEqual(details.status_code, 200)
            self.assertEqual([row["symbol"] for row in details.data["stocks"]], ["AAPL"])
            self.assertIn("error", details.data["stocks"][0])
            self.assertEqual(self.client.get("/api/stocks/watchlist/", {"symbol": ["AAPL"] * 6}).status_code, 400)
            finance.assert_called_once_with("/v8/finance/chart/AAPL", range="1mo", interval="1d")

    def test_watchlist_marks_missing_history_without_dropping_stock(self):
        Stock.objects.create(
            user=self.user,
            ticker="AAPL",
            name="Apple Inc.",
            quantity=0,
            price_per_share=0,
        )
        with patch("api.views.stocks._finance_data", return_value={"chart": {"result": []}}):
            response = self.client.get("/api/stocks/watchlist/")

        self.assertEqual(response.status_code, 200)
        stock = response.data["stocks"][0]
        self.assertEqual(stock["symbol"], "AAPL")
        self.assertEqual(stock["history"], [])
        self.assertIn("error", stock)

    def test_watchlist_marks_network_failure_without_crashing(self):
        Stock.objects.create(
            user=self.user,
            ticker="AAPL",
            name="Apple Inc.",
            quantity=0,
            price_per_share=0,
        )
        with patch(
            "api.views.stocks._finance_data",
            side_effect=requests.ConnectionError("offline"),
        ):
            response = self.client.get("/api/stocks/watchlist/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["stocks"][0]["history"], [])
        self.assertIn("error", response.data["stocks"][0])


class EndToEndApplicationTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_registration_returns_jwt_tokens(self):
        response = self.client.post(
            "/api/user/register/",
            {"username": "registered-user", "password": "StrongPass123!"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        AccessToken(response.data["access"])
        self.assertTrue(
            User.objects.filter(username="registered-user").exists()
        )

    def test_login_returns_access_and_refresh_tokens(self):
        User.objects.create_user(
            username="login-user", password="StrongPass123!"
        )
        response = self.client.post(
            "/api/token/",
            {"username": "login-user", "password": "StrongPass123!"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_transaction_create_list_and_stats(self):
        user = User.objects.create_user(
            username="transaction-user", password="test"
        )
        self.client.force_authenticate(user=user)

        create_response = self.client.post(
            "/api/transactions/",
            {
                "amount": "-25.50",
                "category": "groceries",
                "timestamp": "2026-11-19T12:00:00Z",
                "particulars": "Weekly groceries",
                "currency": "USD",
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, 201)

        list_response = self.client.get(
            "/api/transactions/", {"ordering": "-timestamp"}
        )
        self.assertEqual(list_response.status_code, 200)
        transactions = (
            list_response.data
            if isinstance(list_response.data, list)
            else list_response.data["results"]
        )
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0]["particulars"], "Weekly groceries")

        stats_response = self.client.get("/api/transaction-stats/")
        self.assertEqual(stats_response.status_code, 200)
        self.assertEqual(stats_response.data, [{"category": "groceries", "amount": 25.5}])

    def synthetic_pdf(self):
        with pymupdf.open() as document:
            page = document.new_page()
            page.insert_text((72, 72), "Synthetic bank statement for tests")
            return SimpleUploadedFile("statement.pdf", document.tobytes(), content_type="application/pdf")

    @override_settings(API_KEY="")
    def test_bank_statement_missing_key_returns_503(self):
        user = User.objects.create_user(username="statement-user", password="test")
        self.client.force_authenticate(user=user)
        response = self.client.post(
            "/api/bank-statement/",
            {"file": self.synthetic_pdf(), "allow_external_processing": "true"},
            format="multipart",
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("not configured", response.data["error"].lower())

    @override_settings(API_KEY="test-key")
    def test_bank_statement_returns_and_persists_parsed_transactions(self):
        user = User.objects.create_user(username="statement-success-user", password="test")
        self.client.force_authenticate(user=user)
        parsed = [{
            "amount": -12.5,
            "timestamp": "2026-11-19",
            "category": "groceries",
            "particulars": "Test market",
            "currency": "USD",
        }]

        with patch("api.services.statements.pdf_parser.client") as fake_client:
            fake_client.models.generate_content.return_value = SimpleNamespace(text=json.dumps(parsed))
            response = self.client.post(
                "/api/bank-statement/",
                {"file": self.synthetic_pdf(), "allow_external_processing": "true"},
                format="multipart",
            )
            fake_client.files.upload.assert_not_called()

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["response"][0]["amount"], "-12.50")
        self.assertTrue(
            Transaction.objects.filter(user=user, particulars="Test market", amount="-12.50").exists()
        )
