import logging
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from django.core.cache import cache
from rest_framework import status, views
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from api.models import Stock

logger = logging.getLogger(__name__)
FINANCE_URL = "https://query1.finance.yahoo.com"
TICKER_LENGTH = Stock._meta.get_field("ticker").max_length
NAME_LENGTH = Stock._meta.get_field("name").max_length


def _finance_data(path, **params):
    response = requests.get(
        FINANCE_URL + path,
        params=params,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=6,
    )
    response.raise_for_status()
    return response.json()


def _search_stocks(query):
    cache_key = f"stock-search:{query.casefold()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    data = _finance_data("/v1/finance/search", q=query, quotesCount=12, newsCount=0)
    results = {}
    for item in data["quotes"]:
        if item.get("quoteType") != "EQUITY":
            continue
        symbol = item.get("symbol", "").upper()
        name = item.get("longname") or item.get("shortname")
        if not symbol or len(symbol) > TICKER_LENGTH or not name:
            continue
        stock = {
            "symbol": symbol,
            "name": name,
            "exchange": item.get("exchDisp") or item.get("exchange") or "Unknown",
        }
        results[symbol] = stock
        cache.set(f"stock-info:{symbol}", stock, timeout=3600)

    ordered = sorted(results.values(), key=lambda stock: stock["symbol"] != query.upper())
    cache.set(cache_key, ordered, timeout=300)
    return ordered


def _stock_info(symbol):
    cached = cache.get(f"stock-info:{symbol}")
    if cached is not None:
        return cached
    return next((item for item in _search_stocks(symbol) if item["symbol"] == symbol), None)


def _stock_history(symbol):
    cache_key = f"stock-history:{symbol}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    data = _finance_data(
        f"/v8/finance/chart/{quote(symbol, safe='')}", range="1mo", interval="1d"
    )
    results = data["chart"]["result"]
    if not results:
        return []

    chart = results[0]
    timezone = chart["meta"].get("exchangeTimezoneName", "UTC")
    exchange_zone = ZoneInfo(timezone)
    closes = chart["indicators"]["quote"][0]["close"]
    history = [
        {
            "date": datetime.fromtimestamp(timestamp, exchange_zone).date().isoformat(),
            "price": price,
        }
        for timestamp, price in zip(chart.get("timestamp", []), closes)
        if isinstance(price, (int, float)) and math.isfinite(price)
    ]
    if history:
        cache.set(cache_key, history, timeout=300)
    return history


def _watchlist_entry(stock):
    symbol = stock["ticker"]
    entry = {"symbol": symbol, "name": stock["name"], "history": []}
    try:
        entry["history"] = _stock_history(symbol)
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError, ZoneInfoNotFoundError):
        logger.warning("Could not load stock history for %s", symbol, exc_info=True)
    if not entry["history"]:
        entry["error"] = "No price history available for this ticker right now."
    return entry


class WatchlistView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        stocks = list(Stock.objects.filter(user=request.user).values("ticker", "name"))
        if request.query_params.get("include_history") == "false":
            return Response({"stocks": [{"symbol": stock["ticker"], "name": stock["name"]} for stock in stocks]})
        if stocks:
            with ThreadPoolExecutor(max_workers=min(5, len(stocks))) as pool:
                stocks = list(pool.map(_watchlist_entry, stocks))
        return Response({"stocks": stocks})

    def post(self, request):
        new_symbol = request.data.get("symbol")
        if not isinstance(new_symbol, str) or not new_symbol.strip():
            return Response({"error": "Symbol is required."}, status=status.HTTP_400_BAD_REQUEST)

        symbol = new_symbol.strip().upper()
        if len(symbol) > TICKER_LENGTH:
            return Response({"error": "Invalid stock symbol."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            stock_info = _stock_info(symbol)
        except (requests.RequestException, ValueError, KeyError, TypeError):
            logger.warning("Could not validate stock symbol %s", symbol, exc_info=True)
            return Response(
                {"error": f"Unable to verify ticker {symbol} right now."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        if stock_info is None:
            return Response(
                {"error": f"No stock found for ticker {symbol}."},
                status=status.HTTP_404_NOT_FOUND,
            )

        Stock.objects.get_or_create(
            user=request.user,
            ticker=symbol,
            defaults={"name": stock_info["name"][:NAME_LENGTH], "quantity": 0, "price_per_share": 0},
        )
        symbols = Stock.objects.filter(user=request.user).values_list("ticker", flat=True)
        return Response({"symbols": list(symbols)})


class StockSearchView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = (request.GET.get("query") or "").strip()
        if not 1 <= len(query) <= 100:
            return Response(
                {"error": "Enter a stock symbol or company name."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            results = _search_stocks(query)
        except (requests.RequestException, ValueError, KeyError, TypeError):
            logger.warning("Stock search request failed", exc_info=True)
            return Response(
                {"error": "Stock search is temporarily unavailable. Please try again."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        if not results:
            return Response({"error": "No matching stocks found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(results)
