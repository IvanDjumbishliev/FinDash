import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from django.core.cache import cache
from django.utils import timezone

from api.views.stocks import _finance_data

MAX_SYMBOLS = 25
MAX_LOOKBACK = timedelta(days=1827)


@dataclass(frozen=True)
class MarketHistory:
    currency: str | None = None
    zone: object = UTC
    prices: dict = field(default_factory=dict)
    splits: dict = field(default_factory=dict)
    company: str | None = None
    sector: str | None = None
    retrieved_at: datetime | None = None
    status: str = "unavailable"


def price_or_none(raw):
    if type(raw) not in (int, float, str) or len(str(raw)) > 64:
        return None
    try:
        price = Decimal(str(raw))
    except InvalidOperation:
        return None
    return price if price.is_finite() and Decimal("1e-16") <= price < Decimal("1e14") else None


def positive_integer(raw):
    if type(raw) in (int, float) and 0 < raw <= 1_000_000 and raw == int(raw):
        return int(raw)
    raise ValueError("Invalid split ratio.")


def local_day(timestamp, zone):
    if type(timestamp) not in (int, float):
        raise ValueError("Invalid market timestamp.")
    return datetime.fromtimestamp(timestamp, UTC).astimezone(zone).date()


def name(value):
    return " ".join(value.split())[:150] if isinstance(value, str) and value.strip() else None


def parse_history(payload, symbol, fetched_at):
    chart = payload["chart"]["result"][0]
    meta = chart["meta"]
    if meta.get("symbol") != symbol or not re.fullmatch(r"[A-Za-z]{3}", meta.get("currency", "")):
        raise ValueError("Unverified ticker metadata.")
    zone = ZoneInfo(meta["exchangeTimezoneName"])
    timestamps = chart["timestamp"]
    closes = chart["indicators"]["quote"][0]["close"]
    prices = {}
    for stamp, close in zip(timestamps, closes, strict=True):
        day = local_day(stamp, zone)
        value = price_or_none(close)
        prices[day] = None if day in prices and prices[day] != value else value
    splits = {}
    status = "available" if prices else "unavailable"
    try:
        events = chart.get("events", {}).get("splits", {})
        for event in events.values():
            day = local_day(event["date"], zone)
            ratio = (positive_integer(event["numerator"]), positive_integer(event["denominator"]))
            text_ratio = event.get("splitRatio")
            if text_ratio is not None and text_ratio != f"{ratio[0]}:{ratio[1]}":
                raise ValueError("Conflicting published split ratios.")
            if day > fetched_at.astimezone(zone).date():
                continue
            if day in splits and splits[day] != ratio:
                raise ValueError("Conflicting splits on the same session.")
            splits[day] = ratio
    except (AttributeError, KeyError, TypeError, OverflowError, OSError, ValueError):
        status = "unverified_splits"
    return MarketHistory(
        currency=meta["currency"], zone=zone, prices=prices, splits=splits, retrieved_at=fetched_at, status=status,
        company=name(meta.get("longName") or meta.get("shortName")), sector=name(meta.get("sector")),
    )


def market_history(symbol, start, today):
    key = f"virtual-portfolio-history:v1:{symbol}:{start}:{today}"
    result = cache.get(key)
    if result is not None:
        return result
    fetched_at = timezone.now()
    try:
        # Include the most recent split events, even for a report ending earlier.
        result = parse_history(_finance_data(
            f"/v8/finance/chart/{quote(symbol, safe='')}",
            period1=int(datetime.combine(start - timedelta(days=2), time.min, UTC).timestamp()),
            period2=int(datetime.combine(today + timedelta(days=2), time.min, UTC).timestamp()),
            interval="1d", events="splits", includeAdjustedClose="false",
        ), symbol, fetched_at)
    except (requests.RequestException, AttributeError, IndexError, KeyError, TypeError, ValueError,
            OSError, OverflowError, ZoneInfoNotFoundError):
        result = MarketHistory()
    cache.set(key, result, 900 if result.status == "available" else 60)
    return result


def historical_data(symbol_starts, today):
    symbols = sorted(symbol_starts, key=lambda symbol: (not symbol.startswith("^"), symbol))
    evaluated = symbols[:MAX_SYMBOLS]
    results = {}
    if evaluated:
        with ThreadPoolExecutor(max_workers=min(5, len(evaluated))) as pool:
            values = pool.map(lambda symbol: market_history(symbol, symbol_starts[symbol], today), evaluated)
            results.update(zip(evaluated, values, strict=True))
    results.update({symbol: MarketHistory(status="quote_limit") for symbol in symbols[MAX_SYMBOLS:]})
    return results


def company_metadata(symbol, history):
    if history.company and history.sector:
        return history.company, history.sector
    key = f"virtual-portfolio-company:v1:{symbol}"
    cached = cache.get(key)
    if cached is None:
        try:
            quotes = _finance_data("/v1/finance/search", q=symbol, quotesCount=5, newsCount=0)["quotes"]
            row = next((entry for entry in quotes if entry.get("symbol") == symbol), {})
            cached = (name(row.get("longname") or row.get("shortname")),
                      name(row.get("sectorDisp") or row.get("sector")))
        except (requests.RequestException, AttributeError, KeyError, TypeError, ValueError):
            cached = (None, None)
        cache.set(key, cached, 3600 if any(cached) else 300)
    return history.company or cached[0], history.sector or cached[1]
