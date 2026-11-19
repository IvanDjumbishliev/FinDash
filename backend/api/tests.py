from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
import pandas as pd

from api.models import Stock, Transaction


class DealEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        cache.clear()

    @override_settings(API_KEY=None)
    def test_store_endpoints_return_empty_deals_when_not_configured(self):
        for store in ("lidl", "kaufland"):
            with self.subTest(store=store):
                response = self.client.get(f"/api/leaflet/{store}/")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["response"], [])
                self.assertIn("not configured", response.data["notice"].lower())

    def test_billa_endpoint_reports_unavailable_without_error(self):
        response = self.client.get("/api/leaflet/billa/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["response"], [])
        self.assertFalse(response.data["available"])
        self.assertIn("not yet available", response.data["notice"].lower())

    @override_settings(API_KEY=None)
    def test_search_returns_helpful_response_when_not_configured(self):
        response = self.client.post(
            "/api/leaflet/user/", {"prompt": "milk"}, format="json"
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["response"], [])
        self.assertIn("not configured", response.data["error"].lower())

    @override_settings(API_KEY="test-key")
    def test_search_returns_empty_list_when_ai_has_no_matches(self):
        cache.set("last_fetch_timestamp_kaufland", "today")
        cache.set("today_kaufland", ["kaufland leaflet"])
        cache.set("last_fetch_timestamp_lidl", "today")
        cache.set("today_lidl", ["lidl leaflet"])
        fake_client = SimpleNamespace(
            models=SimpleNamespace(
                generate_content=lambda **kwargs: SimpleNamespace(text="[]")
            )
        )
        with patch("api.views.leaflet_user.client", fake_client):
            response = self.client.post(
                "/api/leaflet/user/", {"prompt": "milk"}, format="json"
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["response"], [])

    @override_settings(API_KEY="test-key")
    def test_search_returns_helpful_response_when_leaflets_are_missing(self):
        response = self.client.post(
            "/api/leaflet/user/", {"prompt": "milk"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["response"], [])
        self.assertIn("not available", response.data["error"].lower())


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
            {"error": "AI features are not configured. Add API_KEY to backend/.env"},
        )

    @override_settings(API_KEY=None)
    def test_summary_returns_503_when_api_key_is_missing_even_without_transactions(self):
        response = self.client.get("/api/summary/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.data,
            {"error": "AI features are not configured. Add API_KEY to backend/.env"},
        )

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

    @override_settings(API_KEY="test-key")
    def test_chat_uses_google_genai_generate_content(self):
        fake_client = SimpleNamespace(
            models=SimpleNamespace(
                generate_content=Mock(
                    return_value=SimpleNamespace(text="Helpful answer")
                )
            )
        )
        with patch("api.views.assistant.client", fake_client):
            response = self.client.post(
                "/api/chat/", {"prompt": "How can I save?"}, format="json"
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data, "Helpful answer")
        fake_client.models.generate_content.assert_called_once()
        call = fake_client.models.generate_content.call_args.kwargs
        self.assertEqual(call["model"], "gemini-2.0-flash")
        self.assertIsInstance(call["contents"], list)

    @override_settings(API_KEY="test-key")
    def test_summary_uses_google_genai_generate_content(self):
        Transaction.objects.create(
            user=self.user,
            amount="12.50",
            category=Transaction.Category.GROCERIES,
            particulars="Groceries",
            currency="USD",
        )
        fake_client = SimpleNamespace(
            models=SimpleNamespace(
                generate_content=Mock(
                    return_value=SimpleNamespace(
                        text='[{"title":"Spending","description":"Track groceries."}]'
                    )
                )
            )
        )
        with patch("api.views.user_summary.client", fake_client):
            response = self.client.get("/api/summary/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]["title"], "Spending")
        fake_client.models.generate_content.assert_called_once()
        call = fake_client.models.generate_content.call_args.kwargs
        self.assertEqual(call["model"], "gemini-2.0-flash")
        self.assertIn(
            "response_schema",
            call["config"],
        )


class StockEndpointTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="stock-user", password="test")
        self.other_user = User.objects.create_user(
            username="other-stock-user", password="test"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_search_returns_common_ticker_results(self):
        with patch("api.views.stocks.yf.Ticker") as ticker_factory:
            ticker_factory.return_value.info = {
                "symbol": "AAPL",
                "longName": "Apple Inc.",
                "exchange": "NMS",
            }
            for symbol in ("AAPL", "MSFT", "TSLA"):
                with self.subTest(symbol=symbol):
                    ticker_factory.return_value.info["symbol"] = symbol
                    response = self.client.get(
                        "/api/stocks/search/", {"query": symbol.lower()}
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.data[0]["symbol"], symbol)

    def test_search_returns_clean_error_for_missing_ticker_data(self):
        with patch("api.views.stocks.yf.Ticker") as ticker_factory:
            ticker_factory.return_value.info = {}
            response = self.client.get("/api/stocks/search/", {"query": "INVALID"})

        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.data)

    def test_search_returns_clean_error_for_yfinance_failure(self):
        with patch("api.views.stocks.yf.Ticker", side_effect=RuntimeError("offline")):
            response = self.client.get("/api/stocks/search/", {"query": "AAPL"})

        self.assertEqual(response.status_code, 502)
        self.assertIn("error", response.data)

    def test_adding_stock_persists_uppercase_ticker_for_current_user(self):
        with patch("api.views.stocks.yf.Ticker") as ticker_factory:
            ticker_factory.return_value.info = {
                "symbol": "AAPL",
                "longName": "Apple Inc.",
            }
            response = self.client.post(
                "/api/stocks/watchlist/", {"symbol": " aapl "}, format="json"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["symbols"], ["AAPL"])
        self.assertTrue(
            Stock.objects.filter(
                user=self.user, ticker="AAPL", name="Apple Inc."
            ).exists()
        )
        self.assertFalse(Stock.objects.filter(user=self.other_user).exists())

    def test_invalid_ticker_is_not_saved(self):
        with patch("api.views.stocks.yf.Ticker") as ticker_factory:
            ticker_factory.return_value.info = {}
            response = self.client.post(
                "/api/stocks/watchlist/", {"symbol": "INVALID"}, format="json"
            )

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
        history = pd.DataFrame(
            {"Close": [190.25, 191.5]},
            index=pd.to_datetime(["2026-11-17", "2026-11-18"]),
        )
        with patch("api.views.stocks.yf.Ticker") as ticker_factory:
            ticker_factory.return_value.history.return_value = history
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
        ticker_factory.return_value.history.assert_called_once_with(
            period="1mo", interval="1d", actions=False
        )

    def test_watchlist_marks_missing_history_without_dropping_stock(self):
        Stock.objects.create(
            user=self.user,
            ticker="AAPL",
            name="Apple Inc.",
            quantity=0,
            price_per_share=0,
        )
        with patch("api.views.stocks.yf.Ticker") as ticker_factory:
            ticker_factory.return_value.history.return_value = pd.DataFrame()
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
            "api.views.stocks.yf.Ticker",
            side_effect=RuntimeError("offline"),
        ):
            response = self.client.get("/api/stocks/watchlist/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["stocks"][0]["history"], [])
        self.assertIn("error", response.data["stocks"][0])


class ApplicationFlowTests(TestCase):
    def test_register_login_create_transaction_list_and_stats(self):
        client = APIClient()
        registration = client.post(
            "/api/user/register/",
            {"username": "flow-user", "password": "Secure-test-pass-934!"},
            format="json",
        )
        self.assertEqual(registration.status_code, 201)
        self.assertTrue(registration.data["access"])
        self.assertTrue(registration.data["refresh"])

        login = client.post(
            "/api/token/",
            {"username": "flow-user", "password": "Secure-test-pass-934!"},
            format="json",
        )
        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.data["access"])
        self.assertTrue(login.data["refresh"])
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

        created = client.post(
            "/api/transactions/",
            {
                "amount": "-25.50",
                "category": "groceries",
                "particulars": "Weekly shop",
                "currency": "BGN",
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(str(created.data["amount"]), "-25.50")

        listed = client.get("/api/transactions/", {"limit": 10})
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.data["results"][0]["particulars"], "Weekly shop")

        Transaction.objects.create(
            user_id=registration.data["id"],
            amount="-10.00",
            category=Transaction.Category.GROCERIES,
            particulars="Second shop",
            currency="BGN",
        )
        Transaction.objects.create(
            user_id=registration.data["id"],
            amount="-7.00",
            category=Transaction.Category.TRANSPORT,
            particulars="Bus",
            currency="BGN",
        )
        Transaction.objects.create(
            user_id=registration.data["id"],
            amount="100.00",
            category=Transaction.Category.GENERAL,
            particulars="Refund",
            currency="BGN",
        )
        stats = client.get("/api/transaction-stats/")
        self.assertEqual(stats.status_code, 200)
        self.assertEqual(
            {item["category"]: item["amount"] for item in stats.data},
            {"groceries": 35.5, "transport": 7.0},
        )

    @override_settings(API_KEY="")
    def test_pdf_upload_returns_config_error_without_api_key(self):
        client = APIClient()
        user = User.objects.create_user(username="pdf-no-key", password="test")
        client.force_authenticate(user=user)
        response = client.post(
            "/api/bank-statement/",
            {
                "file": SimpleUploadedFile(
                    "statement.pdf", b"%PDF-1.4 test", content_type="application/pdf"
                )
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("API_KEY", response.data["error"])

    @override_settings(API_KEY="test-key")
    def test_pdf_upload_parses_and_persists_transactions(self):
        client = APIClient()
        user = User.objects.create_user(username="pdf-user", password="test")
        client.force_authenticate(user=user)
        extracted = [
            {
                "amount": -15.25,
                "timestamp": "2026-11-18",
                "category": "groceries",
                "particulars": "Market",
                "currency": "BGN",
            }
        ]
        fake_client = SimpleNamespace(
            files=SimpleNamespace(upload=Mock(return_value="uploaded-pdf")),
            models=SimpleNamespace(
                generate_content=Mock(
                    return_value=SimpleNamespace(text=__import__("json").dumps(extracted))
                )
            ),
        )
        with patch("api.views.pdf_import.client", fake_client):
            response = client.post(
                "/api/bank-statement/",
                {
                    "file": SimpleUploadedFile(
                        "statement.pdf",
                        b"%PDF-1.4 test",
                        content_type="application/pdf",
                    )
                },
                format="multipart",
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["response"], extracted)
        self.assertTrue(
            Transaction.objects.filter(
                user=user,
                amount="-15.25",
                particulars="Market",
                currency="BGN",
            ).exists()
        )
