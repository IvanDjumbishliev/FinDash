import base64
import io
import json
import logging
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from time import time
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from django.core.cache import cache
import pymupdf
from PIL import Image
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


LIDL_SOURCE = "https://www.lidl.bg/"
KAUFLAND_SOURCE = "https://www.kaufland.bg/aktualni-predlozheniya/oferti.html"
FANTASTICO_SOURCE = "https://www.fantastico.bg/special-offers"


def offer_output(offers, catalog):
    if catalog:
        return offers
    return [{key: value for key, value in row.items() if key != "_catalog"} for row in offers]


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "bg-BG,bg;q=0.9,en;q=0.8",
}


def absolute_image_url(url):
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return "https://www.kaufland.bg" + url
    return url


logger = logging.getLogger(__name__)
BROCHURE_PRICE = re.compile(r"\d{1,4}[,.]\d{2}")
BROCHURE_DISCOUNT = re.compile(r"[-−](\d{1,2})%")


def jpeg_data_url(content):
    return "data:image/jpeg;base64," + base64.b64encode(content).decode("ascii")


def lidl_product_offers(html, timestamp, *, catalog=False):
    offers = {}
    soup = BeautifulSoup(html, "html.parser")
    for tile in soup.select("[data-grid-data]"):
        try:
            product = json.loads(tile["data-grid-data"])
        except json.JSONDecodeError:
            continue
        start = product.get("storeStartDate")
        end = product.get("storeEndDate")
        if (start is not None and start > timestamp) or (
            end is not None and end < timestamp
        ):
            continue

        name = product.get("fullTitle") or product.get("title")
        image = (product.get("imageList_V1") or [{}])[0].get("image")
        price = product.get("price") or {}
        requires_membership = price.get("price") is None
        if requires_membership:
            plus = (product.get("lidlPlus") or [{}])[0]
            price = plus.get("price") or {}
        amount = price.get("price")
        if not name or (not catalog and (not image or type(amount) not in (int, float))):
            continue
        if type(amount) not in (int, float):
            amount = None
            requires_membership = False

        currency = price.get("displayedCurrency", "€")
        discount = price.get("discount") or {}
        previous_amount = price.get("oldPrice") or discount.get("deletedPrice")
        percentage = None
        if amount is not None and isinstance(previous_amount, (int, float)) and previous_amount > amount:
            percentage = round((1 - amount / previous_amount) * 100)
        else:
            match = re.search(r"(\d{1,2})\s*[%﹪]\s*по-евтино", discount.get("discountText") or "")
            if match:
                percentage = int(match[1])

        formatted_price = f"{amount:.2f}".replace(".", ",") if amount is not None else ""
        key = (product.get("productId") or name, name, formatted_price, currency, start, end, str(product.get("grammage")))
        offers.setdefault(key, {
            "name": name,
            "price": f"{formatted_price} {currency}" if formatted_price else "",
            "image_url": urljoin("https://www.lidl.bg", image) if image else "",
            "store": "Lidl",
            "discount_percent": percentage,
            "price_note": "Lidl Plus" if requires_membership else "",
            "_catalog": {
                "product_id": product.get("productId"), "name": name, "brand": product.get("brand"),
                "quantity_text": product.get("grammage"), "amount": amount,
                "currency": price.get("displayedCurrency"), "start": start, "end": end,
                "source_url": LIDL_SOURCE, "membership": requires_membership,
            },
        })
    return offer_output(sorted(offers.values(), key=lambda offer: offer["discount_percent"] or 0, reverse=True), catalog)


DEAL_CACHE_KEYS = {
    "lidl": "scraped_deals_lidl_products_v3",
    "kaufland": "scraped_deals_kaufland_current_v2",
    "fantastico": "scraped_deals_fantastico_products_v2",
}


def cached_deal_highlights(now):
    """Read public snapshots and omit expired offers when dates are available."""
    from api.services.grocery_catalog import LOCAL_ZONE, observed_date

    today = now.astimezone(LOCAL_ZONE).date()
    cached = cache.get_many(DEAL_CACHE_KEYS.values())
    highlights = []
    for retailer, key in DEAL_CACHE_KEYS.items():
        count = 0
        for offer in cached.get(key, []):
            if not offer.get("name") or not offer.get("price"):
                continue
            metadata = offer.get("_catalog", {})
            start, start_at = observed_date(metadata.get("start"))
            end, end_at = observed_date(metadata.get("end"))
            if (start and start > today or end and end < today
                    or start_at and start_at > now or end_at and end_at < now):
                continue
            highlights.append({
                "id": f"{retailer}-{count}", "retailer": retailer,
                "product_name": offer["name"], "display_price": offer["price"],
                "expires_on": end.isoformat() if end else None,
            })
            count += 1
            if count == 2:
                break
    return highlights


def scrape_lidl(*, catalog=False):
    cache_key = DEAL_CACHE_KEYS["lidl"]
    cached = cache.get(cache_key)
    if cached is not None and not catalog:
        return offer_output(cached if catalog else [row for row in cached if row["image_url"] and row["price"]], catalog)

    try:
        response = requests.get(
            LIDL_SOURCE, headers=HEADERS, timeout=15
        )
        response.raise_for_status()
        deals = lidl_product_offers(response.text, time(), catalog=True)
    except (requests.RequestException, RuntimeError):
        logger.warning("Could not load Lidl's current offers")
        return []

    if deals:
        cache.set(cache_key, deals, timeout=3600)
    return offer_output(deals if catalog else [row for row in deals if row["image_url"] and row["price"]], catalog)


def extract_ssr_json(html):
    match = re.search(r"window\.SSR\[[^\]]+\]\s*=\s*(\{)", html)
    if not match:
        return None

    start = match.start(1)
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(html)):
        char = html[index]
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start : index + 1])
                except json.JSONDecodeError:
                    return None
    return None


def scrape_kaufland(*, catalog=False):
    cache_key = DEAL_CACHE_KEYS["kaufland"]
    cached = cache.get(cache_key)
    if cached is not None and not catalog:
        return offer_output(cached, catalog)

    try:
        response = requests.get(
            KAUFLAND_SOURCE,
            headers=HEADERS,
            timeout=20,
        )
        response.raise_for_status()
        data = extract_ssr_json(response.text)
        if data is None:
            soup = BeautifulSoup(response.text, "html.parser")
            cards = []
            for img in soup.select("img[alt]"):
                alt = re.sub(r"\s+", " ", img.get("alt", "")).strip()
                if alt.startswith("Изображение на ") and len(alt) > 20:
                    cards.append(
                        {
                            "name": alt.replace("Изображение на ", "", 1).strip(),
                            "price": "",
                            "image_url": absolute_image_url(
                                img.get("src") or img.get("data-src")
                            ),
                            "store": "Kaufland",
                            "_catalog": {"source_url": KAUFLAND_SOURCE},
                        }
                    )
            deals = [] if catalog else cards
        else:
            deals = []
            seen = set()
            today = datetime.now(ZoneInfo("Europe/Sofia")).date().isoformat()
            offer_data = data.get("props", {}).get("offerData", {})
            for cycle in offer_data.get("cycles", []):
                for category in cycle.get("categories", []):
                    for offer in category.get("offers", []):
                        start = offer.get("dateFrom")
                        end = offer.get("dateTo")
                        if (start and start > today) or (end and end < today):
                            continue
                        offer_id = offer.get("offerId")
                        key = (offer_id, offer.get("unit"), start, end)
                        if offer_id and key in seen:
                            continue
                        name = re.sub(
                            r"\s+",
                            " ",
                            " ".join(
                                part
                                for part in (
                                    offer.get("title"),
                                    offer.get("subtitle"),
                                    offer.get("unit"),
                                )
                                if part
                            ),
                        ).strip()
                        price = offer.get("formattedPrice")
                        if not price:
                            price_value = offer.get("price")
                            price = (
                                f"{price_value} €" if price_value is not None else ""
                            )
                        if name:
                            if offer_id:
                                seen.add(key)
                            deals.append(
                                {
                                    "name": name,
                                    "price": price,
                                    "image_url": absolute_image_url(
                                        offer.get("listImage")
                                        or (offer.get("detailImages") or [""])[0]
                                    ),
                                    "store": "Kaufland",
                                    "_catalog": {
                                        "product_id": offer.get("productId"), "offer_id": offer_id,
                                        "brand": offer.get("brand"), "category": category.get("title") or category.get("name"),
                                        "quantity_text": offer.get("unit"),
                                        "price_text": offer.get("formattedPrice"),
                                        "amount": offer.get("price"), "currency": offer.get("currency"),
                                        "start": start, "end": end, "source_url": KAUFLAND_SOURCE,
                                    },
                                }
                            )
    except Exception:
        deals = []

    if deals or not catalog:
        cache.set(cache_key, deals, timeout=60 * 60)
    return offer_output(deals, catalog)


def fantastico_words(content):
    """Read the viewer's searchable words and their page coordinates."""
    words = []
    for line in content.splitlines():
        value, *segments = line.split("\x02")
        if len(segments) < 5:
            continue
        try:
            x, y, _, height = map(int, segments[:4])
            offsets = segments[4].split("\x04", 1)[0].split("\x03")
            width = int(offsets[-1])
        except ValueError:
            continue
        box = pymupdf.Rect(x / 10, y / 10, (x + width) / 10, (y + height) / 10)
        words.append((value, box))
    return words


def fantastico_page_offers(search_text, image_content, width, height):
    words = fantastico_words(search_text)
    currency_tags = [box for word, box in words if word.startswith("€")]
    prices = [
        (word, box)
        for word, box in words
        if BROCHURE_PRICE.fullmatch(word)
        and any(
            -5 <= tag.x0 - box.x1 <= 55 and 0 < tag.y0 - box.y0 <= 50
            for tag in currency_tags
        )
    ]
    descriptions = defaultdict(list)
    for word, box in words:
        if box.height < 10 or (word, box) in prices:
            continue
        candidates = [
            (abs(box.x0 - price.x0) + abs(box.y0 - price.y0), index)
            for index, (_, price) in enumerate(prices)
            if -85 <= box.x0 - price.x0 <= 95 and box.y1 <= price.y0 <= box.y0 + 95
        ]
        if candidates:
            descriptions[min(candidates)[1]].append((word, box))

    offers = []
    with Image.open(io.BytesIO(image_content)) as source:
        image = source.convert("RGB")
        for index, (price, box) in enumerate(prices):
            name_words = sorted(descriptions[index], key=lambda item: (item[1].y0, item[1].x0))
            name = " ".join(word for word, _ in name_words)
            if sum(char.isalpha() for char in name) < 4:
                continue
            discount = next(
                (
                    match
                    for word, tag in words
                    if abs(tag.x0 - box.x0) < 65 and 15 < tag.y0 - box.y0 < 60
                    if (match := BROCHURE_DISCOUNT.fullmatch(word))
                ),
                None,
            )

            # The substrate has the retailer photography at the same scale as
            # the searchable text. Frame the product immediately above its label.
            center = (box.x0 + box.x1) / 2
            # Labels near the left edge have their photos farther to the right.
            shift = width * 0.06 if center < width * 0.1 else 0
            left = max(0, center + shift - width * 0.14)
            right = min(width, center + shift + width * 0.10)
            top = max(0, box.y0 - height * 0.29)
            for _, other in prices:
                other_center = (other.x0 + other.x1) / 2
                if abs(other.y0 - box.y0) < height * 0.09:
                    midpoint = (center + other_center) / 2
                    if other_center < center:
                        left = max(left, midpoint)
                    elif other_center > center:
                        right = min(right, midpoint)
                elif top < other.y1 < box.y0 and left < other_center < right:
                    top = max(top, other.y1)
            bottom = min(box.y0, name_words[0][1].y0)
            if bottom - top < height * 0.08:
                bottom = min(height, box.y1 + height * 0.04)
            if bottom <= top or right <= left:
                continue
            crop = image.crop((
                left * image.width / width, top * image.height / height,
                right * image.width / width, bottom * image.height / height,
            ))
            if min(crop.size) < 2:
                continue
            crop.thumbnail((320, 320))
            with io.BytesIO() as encoded:
                crop.save(encoded, format="JPEG", quality=80)
                image_url = jpeg_data_url(encoded.getvalue())
            offers.append({
                "name": name,
                "price": f"{price.replace('.', ',')} €",
                "image_url": image_url,
                "store": "Fantastico",
                "discount_percent": int(discount[1]) if discount else None,
            })
    return offers


def allowed_brochure_origin(url, *domains):
    if any(character.isspace() or character == "\\" for character in url):
        return False
    parts = urlsplit(url)
    host = parts.hostname or ""
    return (
        parts.scheme == "https" and parts.username is None and parts.password is None
        and parts.port in (None, 443)
        and any(host == domain or host.endswith("." + domain) for domain in domains)
    )


def reject_brochure_redirect(response):
    if 300 <= response.status_code < 400:
        raise ValueError("Unexpected retailer redirect.")
    response.raise_for_status()


def scrape_fantastico(*, catalog=False):
    cache_key = DEAL_CACHE_KEYS["fantastico"]
    cached = cache.get(cache_key)
    if cached is not None and not catalog:
        return offer_output(cached, catalog)

    try:
        listing = requests.get(
            FANTASTICO_SOURCE, headers=HEADERS, timeout=10, allow_redirects=False
        )
        reject_brochure_redirect(listing)
        soup = BeautifulSoup(listing.text, "html.parser")
        selector = ".brochure-switch[data-url]"
        current = soup.select_one(f"{selector}.active") or soup.select_one(selector)
        if current is not None:
            flipbook_url = urljoin(listing.url, current["data-url"])
        else:
            # The brochure detail URL also carries the FlippingBook publication ID.
            detail = soup.select_one('a[href*="/special-offers/"][href*="id="]')
            if detail is None:
                return []
            publication = parse_qs(urlsplit(detail["href"]).query).get("id", [""])[0]
            if not publication.isascii() or not publication.isdecimal():
                return []
            flipbook_url = f"https://online.flippingbook.com/view/{publication}/"
        if not allowed_brochure_origin(flipbook_url, "online.flippingbook.com"):
            return []
        flipbook = requests.get(
            flipbook_url, headers={**HEADERS, "Referer": listing.url}, timeout=10, allow_redirects=False
        )
        reject_brochure_redirect(flipbook)

        policy_match = re.search(
            r"var initialPolicies\s*=\s*(\[.*?\]);", flipbook.text, re.S
        )
        content_match = re.search(r"ContentRoot:\s*['\"]([^'\"]+)['\"]", flipbook.text)
        if not policy_match or not content_match:
            return []
        content_root = urljoin(flipbook_url, content_match[1]).rstrip("/") + "/"
        if not allowed_brochure_origin(content_root, "flippingbook.com", "cloudfront.net"):
            return []
        content_parts = urlsplit(content_root)
        policy = next(
            (
                item
                for item in json.loads(policy_match[1])
                if (
                    (prefix := urlsplit(item.get("PathPrefix", "").removeprefix(":"))).hostname
                    in (None, content_parts.hostname)
                    and prefix.path.rstrip("/") == content_parts.path.rstrip("/")
                )
            ),
            None,
        )
        if policy is None:
            return []

        params = {
            "Key-Pair-Id": policy["KeyId"],
            "Policy": policy["Policy"],
            "Signature": policy["Signature"],
        }

        def fetch_asset(path):
            response = requests.get(
                content_root + path,
                params=params,
                headers={**HEADERS, "Referer": flipbook_url},
                timeout=8,
                allow_redirects=False,
            )
            reject_brochure_redirect(response)
            return response

        pages = fetch_asset("common/pager.json").json()["pages"]
        defaults = pages["defaults"]
        page_numbers = sorted(int(key) for key in pages if key.isdecimal())[:100]
    except (requests.RequestException, ValueError, KeyError):
        logger.warning("Could not load Fantastico's current brochure")
        return []

    def read_page(number):
        try:
            page = pages[str(number)]
            search = fetch_asset(f"flash/search/search{number:04d}.xml")
            search_text = search.content.decode("utf-8-sig")
            if "€" not in search_text:
                return []
            image = fetch_asset(f"common/pages/html5substrates/page{number:04d}_2.webp")
            return fantastico_page_offers(
                search_text,
                image.content,
                page.get("width", defaults["width"]),
                page.get("height", defaults["height"]),
            )
        except (requests.RequestException, ValueError, OSError, KeyError, TypeError):
            logger.warning("Could not read Fantastico brochure page %s", number)
            return None

    if catalog:
        results = []
        for number in page_numbers:
            page = read_page(number)
            if page is None:
                return []
            results.append(page)
    else:
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(read_page, page_numbers))
    offers = [offer for page in results if page for offer in page]

    deals = {}
    brochure_source = urlsplit(flipbook_url)._replace(query="", fragment="").geturl()
    for offer in sorted(offers, key=lambda item: item["discount_percent"] or 0, reverse=True):
        deals.setdefault((offer["name"].casefold(), offer["price"]), {
            **offer, "_catalog": {"source_url": brochure_source, "price_text": offer["price"]},
        })
    result = list(deals.values())
    if result:
        cache.set(cache_key, result, timeout=3600)
    return offer_output(result, catalog)


def catalog_deals(retailer, store):
    """Serve verified, still-current advertised offers during a retailer outage."""
    from api.models import GroceryOffer

    offers = (GroceryOffer.objects.current().filter(retailer=retailer, availability_status="advertised")
              .exclude(image_url="").order_by("product_name", "pk")[:100])
    symbols = {"EUR": "€", "BGN": "лв."}
    return [{
        "name": offer.product_name,
        "price": f"{offer.price:.2f}".replace(".", ",") + f" {symbols.get(offer.currency, offer.currency)}",
        "image_url": offer.image_url,
        "store": store,
        "price_note": "Lidl Plus" if retailer == "lidl" and offer.requires_membership else
        "Membership required" if offer.requires_membership else "",
    } for offer in offers]


class LidlDealsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        return Response(scrape_lidl() or catalog_deals("lidl", "Lidl"))


class KauflandDealsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        return Response(scrape_kaufland(), status=200)


class FantasticoDealsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        return Response(scrape_fantastico() or catalog_deals("fantastico", "Fantastico"))
