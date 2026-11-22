import logging
from collections.abc import Mapping
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from django.core.cache import cache
from django.utils import timezone
from rest_framework import status, views
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from api.models import Stock
from api.throttles import SensitiveEndpointThrottle

logger = logging.getLogger(__name__)
FINANCE_URL = "https://query1.finance.yahoo.com"
TICKER_LENGTH = Stock._meta.get_field("ticker").max_length
NAME_LENGTH = Stock._meta.get_field("name").max_length
MARKET_BATCH_SIZE = 5


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


def _market_number(value, *, allow_zero=False):
    if type(value) in (int, float) and 0 <= value < 1e16 and (value > 0 or allow_zero):
        return value
    return None


def _market_details(meta):
    currency = meta.get("currency")
    timestamp = _market_number(meta.get("regularMarketTime"))
    try:
        quoted_at = datetime.fromtimestamp(timestamp, UTC) if timestamp is not None else None
    except (OverflowError, OSError, ValueError):
        quoted_at = None
    now = timezone.now()
    if quoted_at and quoted_at > now + timedelta(minutes=5):
        quoted_at = None
    exchange = meta.get("fullExchangeName") or meta.get("exchangeName")
    return {
        "exchange": exchange[:100] if isinstance(exchange, str) else None,
        "currency": currency if isinstance(currency, str) and re.fullmatch(r"[A-Za-z]{3}", currency) else None,
        "price": _market_number(meta.get("regularMarketPrice")) if quoted_at else None,
        "quoted_at": quoted_at.isoformat() if quoted_at else None,
        "day_low": _market_number(meta.get("regularMarketDayLow")) if quoted_at else None,
        "day_high": _market_number(meta.get("regularMarketDayHigh")) if quoted_at else None,
        "year_low": _market_number(meta.get("fiftyTwoWeekLow")),
        "year_high": _market_number(meta.get("fiftyTwoWeekHigh")),
        "volume": _market_number(meta.get("regularMarketVolume"), allow_zero=True) if quoted_at else None,
    }


def _stock_market(symbol):
    cache_key = f"stock-market:v1:{symbol}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    data = _finance_data(
        f"/v8/finance/chart/{quote(symbol, safe='')}", range="1mo", interval="1d"
    )
    results = data["chart"]["result"]
    if not results:
        return {"history": [], "market": {}}

    chart = results[0]
    meta = chart.get("meta") if isinstance(chart, Mapping) else None
    if not isinstance(meta, Mapping) or meta.get("symbol", symbol) != symbol:
        raise ValueError("Unexpected quote ticker.")
    exchange_zone = ZoneInfo(meta.get("exchangeTimezoneName") or "UTC")
    indicators = chart.get("indicators") or {}
    quote_series = (indicators.get("quote") or [{}])[0] if isinstance(indicators, Mapping) else {}
    closes = quote_series.get("close") or [] if isinstance(quote_series, Mapping) else []
    history = [
        {
            "date": datetime.fromtimestamp(timestamp, exchange_zone).date().isoformat(),
            "price": price,
        }
        for timestamp, price in zip(chart.get("timestamp") or [], closes)
        if _market_number(price) is not None and _market_number(timestamp) is not None and timestamp < 253402214400
    ]
    history.sort(key=lambda point: point["date"])
    market_data = {"history": history, "market": _market_details(meta)}
    if history or market_data["market"]["price"] is not None:
        cache.set(cache_key, market_data, timeout=300)
    return market_data


def _watchlist_entry(stock):
    symbol = stock["ticker"]
    entry = {"symbol": symbol, "name": stock["name"], "history": []}
    try:
        entry.update(_stock_market(symbol))
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError, OverflowError, OSError, ZoneInfoNotFoundError):
        logger.warning("Stock history provider unavailable")
    if not entry["history"]:
        entry["error"] = "No price history available for this ticker right now."
    return entry


class WatchlistView(views.APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [SensitiveEndpointThrottle]
    throttle_scope = "stock_provider"

    def get(self, request):
        stocks = Stock.objects.filter(user=request.user).order_by("pk").values("ticker", "name")
        symbols = request.query_params.getlist("symbol")
        if symbols:
            if len(symbols) > MARKET_BATCH_SIZE or any(not symbol or len(symbol) > TICKER_LENGTH for symbol in symbols):
                raise ValidationError({"symbol": "Request up to five saved stock symbols."})
            stocks = stocks.filter(ticker__in=symbols)
        stocks = list(stocks)
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
            logger.warning("Stock quote validation unavailable")
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
    throttle_classes = [SensitiveEndpointThrottle]
    throttle_scope = "stock_provider"

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
            logger.warning("Stock search provider unavailable")
            return Response(
                {"error": "Stock search is temporarily unavailable. Please try again."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        if not results:
            return Response({"error": "No matching stocks found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(results)
