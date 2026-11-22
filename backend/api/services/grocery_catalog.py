import hashlib
import json
import re
import unicodedata
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from requests import RequestException

from django.db import transaction
from django.utils import timezone

from api.models import GroceryCatalogRefresh, GroceryOffer, GroceryRetailer
from api.views.deals import scrape_fantastico, scrape_kaufland, scrape_lidl

ADAPTERS = {
    GroceryRetailer.LIDL: scrape_lidl,
    GroceryRetailer.KAUFLAND: scrape_kaufland,
    GroceryRetailer.FANTASTICO: scrape_fantastico,
}
LOCAL_ZONE = ZoneInfo("Europe/Sofia")
REFRESH_INTERVAL = timedelta(hours=1)
AMOUNT = r"\d+(?:[.,]\d+)?"
MASS = ("kg", "кг", "килограм", "килограма", "g", "г", "гр", "грам", "грама")
VOLUME = ("ml", "мл", "милилитра", "l", "л", "литър", "литра")
COUNT = ("pieces", "piece", "pcs", "pc", "бр", "брой", "броя")
UNIT = "|".join(sorted((*MASS, *VOLUME, *COUNT), key=len, reverse=True))
PACKAGE = re.compile(
    rf"(?<![\w.,/+\-])(?:(?P<prefix>\d+)\s*[x×х*]\s*)?"
    rf"(?P<amount>{AMOUNT})\s*(?P<unit>{UNIT})\.?(?!\w)"
    rf"(?:\s*[x×х*]\s*(?P<suffix>\d+)(?![\w.,]))?",
    re.IGNORECASE,
)
PRICE = re.compile(r"^\s*(\d{1,3}(?:[ .]\d{3})+|\d+)(?:[,.](\d{1,2}))?\s*(€|EUR|BGN|лв\.?)\s*$", re.I)
CURRENCY = {"€": "EUR", "eur": "EUR", "bgn": "BGN", "лв": "BGN", "лв.": "BGN"}
UNCERTAIN_PACKAGE = re.compile(r"(?:^|\s)(?:около|приблизително|до|от|за\s+1?|approx\.?|up to|per)\s*$", re.I)


def string(value, limit):
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def identifier(value):
    return string(str(value), 255) if type(value) in (str, int) else ""


def normalized(value):
    return " ".join(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", value).casefold()))


def web_url(value):
    try:
        parts = urlsplit(value) if isinstance(value, str) and len(value) <= 2048 else None
        if parts and parts.scheme in ("http", "https") and parts.hostname and not parts.username and not parts.password:
            return value
    except ValueError:
        pass
    return ""


def parse_package(value):
    text = unicodedata.normalize("NFKC", value)
    matches = list(PACKAGE.finditer(text))
    if len(matches) != 1:
        return None
    match = matches[0]
    before, after = text[:match.start()], text[match.end():]
    if (UNCERTAIN_PACKAGE.search(before) or re.search(r"\d+\s*[/\-–]\s*$", before)
            or re.match(r"\s*[/\-–]\s*\d", after) or (match["prefix"] and match["suffix"])):
        return None
    size = Decimal(match["amount"].replace(",", "."))
    count = int(match["prefix"] or match["suffix"] or 1)
    unit = match["unit"].casefold()
    if unit in MASS:
        canonical = GroceryOffer.Unit.KILOGRAM
        if unit in ("g", "г", "гр", "грам", "грама"):
            size /= 1000
    elif unit in VOLUME:
        canonical = GroceryOffer.Unit.LITER
        if unit in ("ml", "мл", "милилитра"):
            size /= 1000
    else:
        canonical = GroceryOffer.Unit.ITEM
        if size != size.to_integral_value():
            return None
    quantity = size * count
    if not 0 < count <= 10000 or not Decimal("0.000001") <= quantity < 100000000:
        return None
    rounded = quantity.quantize(Decimal("0.000001"))
    return (rounded, canonical, count, match) if rounded == quantity else None


def observed_price(metadata):
    text = string(metadata.get("price_text"), 100)
    match = PRICE.fullmatch(text)
    if match:
        integer, fraction, symbol = match.groups()
        price = Decimal(integer.replace(" ", "").replace(".", "") + "." + (fraction or "0"))
        currency = CURRENCY[symbol.casefold()]
    elif text:
        return None, None
    else:
        amount = metadata.get("amount")
        try:
            price = Decimal(str(amount)) if type(amount) in (str, int, float) else None
        except InvalidOperation:
            price = None
        currency = CURRENCY.get(string(metadata.get("currency"), 12).casefold())
    if price is None or not price.is_finite() or not 0 < price < 10_000_000_000:
        return None, currency
    rounded = price.quantize(Decimal("0.01"))
    return (rounded, currency) if rounded == price else (None, currency)


def observed_date(value):
    try:
        if type(value) in (int, float):
            instant = datetime.fromtimestamp(value, UTC)
            return instant.astimezone(LOCAL_ZONE).date(), instant
        if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return date.fromisoformat(value), None
    except (ValueError, OverflowError, OSError):
        pass
    return None, None


def normalize_offer(row, observed_at):
    metadata = row.get("_catalog")
    if not isinstance(metadata, dict):
        return None
    name = string(metadata.get("name") or row.get("name"), 255)
    source = web_url(metadata.get("source_url"))
    if not name or not source:
        return None
    brand = string(metadata.get("brand"), 120)
    category = string(metadata.get("category"), 120)
    quantity_text = string(metadata.get("quantity_text"), 200)
    package = parse_package(quantity_text or name)
    quantity, unit, count = package[:3] if package else (None, "", None)
    # A structured quantity may already appear at the end of the display name.
    package_name = unicodedata.normalize("NFKC", name)
    name_package = parse_package(package_name) if package else None
    normalized_name = normalized(name)
    if name_package and name_package[:3] == package[:3]:
        match = name_package[3]
        normalized_name = normalized(package_name[:match.start()] + " " + package_name[match.end():]) or normalized_name
    if not normalized_name:
        return None

    start, starts_at = observed_date(metadata.get("start"))
    end, expires_at = observed_date(metadata.get("end"))
    if (start and end and end < start) or (starts_at and expires_at and expires_at < starts_at):
        return None
    price, currency = observed_price(metadata)
    product_id, offer_id = identifier(metadata.get("product_id")), identifier(metadata.get("offer_id"))
    membership = metadata.get("membership") is True
    discount = row.get("discount_percent")
    discount = discount if type(discount) is int and 0 <= discount <= 100 else None
    unit_price = (
        (price / quantity).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        if price is not None and currency and quantity else None
    )
    key = (
        product_id, offer_id, normalized_name, normalized(brand), quantity, unit, count,
        quantity_text if quantity is None else "", starts_at or start, expires_at or end, currency, membership,
        source if not (product_id or offer_id) else "", price if not (product_id or offer_id) else None,
    )
    fingerprint = hashlib.sha256(json.dumps(key, default=str).encode()).hexdigest()
    return {
        "fingerprint": fingerprint, "retailer_product_id": product_id, "retailer_offer_id": offer_id,
        "product_name": name, "normalized_name": normalized_name[:255], "brand": brand, "category": category,
        "price": price, "currency": currency, "quantity": quantity, "measurement_unit": unit,
        "pack_count": count, "unit_price": unit_price, "starts_on": start, "expires_on": end,
        "starts_at": starts_at, "expires_at": expires_at, "image_url": web_url(row.get("image_url")),
        "source_url": source, "last_successful_update": observed_at,
        "availability_status": "advertised" if price is not None else "unverified",
        "requires_membership": membership, "discount_percent": discount,
    }


def refresh_catalog(retailer, *, now=None):
    now = now or timezone.now()
    with transaction.atomic():
        state, _ = GroceryCatalogRefresh.objects.select_for_update().get_or_create(
            retailer=retailer, defaults={"last_attempt_at": now - REFRESH_INTERVAL, "status": "pending"},
        )
        if now - state.last_attempt_at < REFRESH_INTERVAL:
            return "skipped", state.offer_count
        state.last_attempt_at = now
        state.status = "running"
        state.save(update_fields=["last_attempt_at", "status"])
    try:
        rows = ADAPTERS[retailer](catalog=True)
        normalized_rows = {}
        for row in rows:
            offer = normalize_offer(row, now) if isinstance(row, dict) else None
            if offer:
                normalized_rows[offer["fingerprint"]] = GroceryOffer(retailer=retailer, **offer)
    except (RequestException, RuntimeError, ValueError, TypeError, KeyError):
        normalized_rows = {}
    with transaction.atomic():
        state = GroceryCatalogRefresh.objects.select_for_update().get(retailer=retailer)
        if state.last_attempt_at != now:
            return "skipped", state.offer_count
        if not normalized_rows:
            state.status = "unavailable"
            state.save(update_fields=["status"])
            return state.status, state.offer_count
        fields = [
            field.name for field in GroceryOffer._meta.concrete_fields
            if field.name not in ("id", "retailer", "fingerprint")
        ]
        GroceryOffer.objects.bulk_create(
            normalized_rows.values(), update_conflicts=True,
            unique_fields=["retailer", "fingerprint"], update_fields=fields,
        )
        state.last_success_at = now
        state.status = "success"
        state.offer_count = len(normalized_rows)
        state.save(update_fields=["last_success_at", "status", "offer_count"])
        return state.status, state.offer_count
