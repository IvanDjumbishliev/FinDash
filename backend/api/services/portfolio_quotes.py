import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

import requests
from django.core.cache import cache
from django.utils import timezone

from api.views.stocks import _finance_data

MAX_TICKERS_PER_VALUATION = 25
MAX_QUOTE_AGE = timedelta(days=7)


def market_quote(symbol):
    key = f"virtual-portfolio-market-quote:v1:{symbol}"
    cached = cache.get(key)
    if cached is None:
        try:
            data = _finance_data(f"/v8/finance/chart/{quote(symbol, safe='')}", range="5d", interval="1d")
            chart = data["chart"]["result"][0]["meta"]
            if not isinstance(chart, dict):
                raise ValueError("Invalid market metadata.")
            if chart.get("symbol") is not None and chart["symbol"] != symbol:
                raise ValueError("Market quote returned a different ticker.")
            raw_price = chart["regularMarketPrice"]
            if type(raw_price) not in (int, float, str) or len(str(raw_price)) > 64:
                raise ValueError("Invalid market price.")
            price = Decimal(str(raw_price))
            if not price.is_finite() or not 0 < price < Decimal("1e14") or price.adjusted() < -16:
                raise ValueError("Invalid market price.")
            currency = chart["currency"]
            if not isinstance(currency, str) or not re.fullmatch(r"[A-Za-z]{3}", currency):
                raise ValueError("Missing quote currency.")
            raw_timestamp = chart["regularMarketTime"]
            if type(raw_timestamp) not in (int, float):
                raise ValueError("Invalid market timestamp.")
            timestamp = datetime.fromtimestamp(raw_timestamp, UTC)
            if timestamp > timezone.now() + timedelta(minutes=5):
                raise ValueError("Invalid market timestamp.")
            cached = {"status": "quoted", "price": price, "currency": currency, "timestamp": timestamp}
        except (
            requests.RequestException, OverflowError, OSError, ValueError,
            InvalidOperation, KeyError, TypeError, IndexError,
        ):
            cached = {"status": "unavailable"}
        cache.set(key, cached, timeout=300 if cached["status"] == "quoted" else 30)

    if cached["status"] == "quoted" and timezone.now() - cached["timestamp"] > MAX_QUOTE_AGE:
        return {**cached, "status": "stale"}
    return cached


def portfolio_quotes(symbols):
    if not symbols:
        return {}
    evaluated = symbols[:MAX_TICKERS_PER_VALUATION]
    with ThreadPoolExecutor(max_workers=min(5, len(evaluated))) as pool:
        result = dict(zip(evaluated, pool.map(market_quote, evaluated), strict=True))
    result.update({symbol: {"status": "quote_limit"} for symbol in symbols[MAX_TICKERS_PER_VALUATION:]})
    return result
