import csv
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from api.models import Portfolio, VirtualTrade
from api.services.portfolio_analytics import calculate_series, daily_return
from api.services.portfolio_history import MarketHistory, parse_history


def day(number):
    return date(2026, 5, number)


def stamp(number):
    return datetime(2026, 5, number, 13, tzinfo=UTC)


def trade(number, side, quantity, price, fees="0", ticker="AAA"):
    return SimpleNamespace(
        timestamp=stamp(number), side=side, ticker=ticker,
        quantity=Decimal(quantity), price=Decimal(price), fees=Decimal(fees),
    )


def market(prices, **extra):
    return MarketHistory(**{
        "currency": "USD", "status": "available",
        "prices": {day(number): Decimal(value) if value is not None else None for number, value in prices.items()},
        "retrieved_at": stamp(20), "company": "Example Company", "sector": "Technology", **extra,
    })


class HistoricalReturnTests(TestCase):
    def report(self, trades, markets, start=1, end=10, benchmark=None):
        with localcontext() as context:
            context.prec = 60
            result, _, _ = calculate_series(trades, markets, "USD", day(start), day(end), day(20), benchmark)
        return result

    def test_funding_withdrawals_fees_and_geometric_linking(self):
        trades = [trade(1, "buy", "1", "100", "1"), trade(3, "buy", "1", "120", "2"), trade(4, "sell", "1", "120", "3")]
        rows = self.report(trades, {"AAA": market({1: "101", 2: "110", 3: "120", 4: "125"})})
        self.assertEqual([row["value"] for row in rows], ["101", "110", "240", "125"])
        self.assertEqual(rows[0]["contributions"], "101")
        self.assertEqual(rows[2]["contributions"], "122")
        self.assertEqual(rows[3]["withdrawals"], "117")
        self.assertAlmostEqual(Decimal(rows[1]["daily_return"]), Decimal(110) / 101 - 1)
        self.assertAlmostEqual(Decimal(rows[2]["daily_return"]), Decimal(240) / 232 - 1)
        self.assertAlmostEqual(Decimal(rows[3]["cumulative_return"]),
                               Decimal(110) / 101 * (Decimal(240) / 232) * (Decimal(242) / 240) - 1)
        self.assertIsNone(daily_return(None, Decimal(2), Decimal(0), Decimal(0)))
        self.assertEqual(daily_return(Decimal(100), Decimal(0), Decimal(0), Decimal(100)), 0)

    def test_aligned_benchmark_starts_at_first_shared_date_and_does_not_fill_gaps(self):
        rows = self.report([trade(1, "buy", "1", "100")], {
            "AAA": market({1: 100, 2: 110, 3: 115, 4: 120}),
            "^GSPC": market({2: 200, 3: None, 4: 210}),
        }, benchmark="^GSPC")
        self.assertIsNone(rows[0]["benchmark_return"])
        self.assertEqual(rows[1]["benchmark_return"], "0")
        self.assertEqual(rows[1]["aligned_portfolio_return"], "0")
        self.assertIsNone(rows[2]["benchmark_return"])
        self.assertIsNone(rows[3]["benchmark_daily_return"])
        self.assertEqual(rows[3]["benchmark_return"], "0.05")
        self.assertAlmostEqual(Decimal(rows[3]["aligned_portfolio_return"]), Decimal(120) / 110 - 1)

        mismatch = self.report([trade(1, "buy", "1", "100")], {
            "AAA": market({1: 100, 2: 110}), "^GSPC": market({1: 200, 2: 210}, currency="EUR"),
        }, benchmark="^GSPC")
        self.assertTrue(all(row["benchmark_return"] is None for row in mismatch))

    def test_missing_prices_break_cumulative_returns_without_inventing_a_close(self):
        rows = self.report([trade(1, "buy", "2", "50")], {
            "AAA": market({1: 50, 2: None, 3: 55, 4: 60}),
        })
        self.assertIsNone(rows[1]["value"])
        self.assertEqual(rows[1]["missing_prices"], {"AAA": "missing_close"})
        self.assertIsNone(rows[2]["daily_return"])
        self.assertIsNone(rows[3]["cumulative_return"])
        self.assertAlmostEqual(Decimal(rows[3]["daily_return"]), Decimal(120) / 110 - 1)

    def test_split_adjusted_prices_use_equivalent_units_including_past_report_ends(self):
        trades = [trade(1, "buy", "10", "20"), trade(3, "sell", "4", "10")]
        prices = {"AAA": market({1: 10, 2: 10, 3: 10}, splits={day(2): (2, 1)})}
        rows = self.report(trades, prices)
        self.assertEqual([row["value"] for row in rows], ["200", "200", "160"])
        self.assertEqual(rows[2]["withdrawals"], "40")
        self.assertEqual(rows[2]["cumulative_return"], "0")
        self.assertEqual(self.report(trades, prices, end=1)[0]["value"], "200")
        unresolved = self.report(trades, {"AAA": market({1: 10, 2: 10}, status="unverified_splits")})
        self.assertEqual(unresolved[0]["missing_prices"], {"AAA": "unverified_splits"})

    def test_history_parser_rejects_unverified_split_events_and_preserves_missing_prices(self):
        result = {"chart": {"result": [{
            "meta": {"symbol": "AAA", "currency": "USD", "exchangeTimezoneName": "UTC"},
            "timestamp": [int(stamp(1).timestamp()), int(stamp(2).timestamp())],
            "indicators": {"quote": [{"close": [None, 10.25]}]},
            "events": {"splits": {"one": {"date": int(stamp(2).timestamp()), "numerator": 2.0, "denominator": 1}}},
        }]}}
        self.assertEqual(parse_history(result, "AAA", stamp(20)).splits, {day(2): (2, 1)})
        self.assertIsNone(parse_history(result, "AAA", stamp(20)).prices[day(1)])
        result["chart"]["result"][0]["events"]["splits"]["one"]["denominator"] = 0
        self.assertEqual(parse_history(result, "AAA", stamp(20)).status, "unverified_splits")


class PortfolioAnalyticsAPITests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user(username="analytics-owner")
        other = users.objects.create_user(username="another-analytics-owner")
        self.portfolio = Portfolio.objects.create(owner=self.owner, name="Analytics portfolio")
        self.foreign = Portfolio.objects.create(owner=other, name="Foreign portfolio")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.url = f"/api/portfolios/{self.portfolio.pk}/analytics/"
        self.query = {"start": "2026-05-01", "end": "2026-05-04", "benchmark": "^GSPC"}

    def test_endpoint_csv_permissions_and_allocation(self):
        for ticker, amount in (("AAA", "1"), ("BBB", "3")):
            record = VirtualTrade.objects.create(
                portfolio=self.portfolio, ticker=ticker, side="buy", quantity=amount,
                price="10", fees=0, currency="USD",
            )
            VirtualTrade.objects.filter(pk=record.pk).update(timestamp=stamp(1))
        markets = {
            "AAA": market({1: 10, 4: 10}, company="Shared Company", sector="Technology"),
            "BBB": market({1: 10, 4: 10}, company="Shared Company", sector="Technology"),
            "^GSPC": market({1: 200, 4: 210}),
        }
        with patch("api.views.portfolio_analytics.timezone.now", return_value=stamp(20)), patch(
            "api.services.portfolio_analytics.historical_data", return_value=markets,
        ):
            result = self.client.get(self.url, self.query)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.headers["Cache-Control"], "no-store")
            report = result.data
            self.assertEqual(report["benchmark"]["aligned_from"], "2026-05-01")
            self.assertEqual(report["allocation"]["companies"], [
                {"label": "Shared Company", "value": "40", "weight": "1"},
            ])
            self.assertEqual(report["allocation"]["concentration"]["company_hhi"], "1")
            self.assertEqual(report["coverage"]["AAA"]["last_close"], "2026-05-04")
            download = self.client.get(self.url + "export/", self.query)
            self.assertEqual(download.status_code, 200)
            self.assertIn("attachment", download.headers["Content-Disposition"])
            rows = list(csv.DictReader(StringIO(download.content.decode())))
            self.assertEqual(rows[-1]["benchmark_return"], "0.05")
            self.assertEqual(rows[-1]["is_virtual"], "True")

        self.assertEqual(APIClient().get(self.url).status_code, 401)
        self.assertEqual(self.client.get(f"/api/portfolios/{self.foreign.pk}/analytics/export/").status_code, 404)

    def test_invalid_ranges_and_benchmarks_make_no_provider_requests(self):
        provider = Mock()
        with patch("api.views.portfolio_analytics.timezone.now", return_value=stamp(20)), patch(
            "api.services.portfolio_analytics.historical_data", provider,
        ):
            for query in ({"benchmark": "../unknown"}, {"start": "2024-01-01"}, {"end": "2026-05-20"}):
                self.assertEqual(self.client.get(self.url, query).status_code, 400)
        provider.assert_not_called()
