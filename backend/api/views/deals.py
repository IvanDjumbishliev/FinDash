import base64
import csv
import io
import json
import logging
import re
import subprocess
from collections import defaultdict
from datetime import date, datetime
from time import monotonic
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from django.core.cache import cache
import pymupdf
from PIL import Image
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


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
PRICE = re.compile(r"(?<![\d.,])(\d{1,4}[,.]\d{2})\s*(€|лв\.?|EUR)(?!\w)", re.I)
DISCOUNT = re.compile(r"[-−]\s*(\d{1,2})\s*%")
OFFER_COPY = re.compile(
    r"цена|опаковка|виж повече|безплатно|гаранция|срок на|валидн|"
    r"предложения|по-евтино|за килограм|\b(?:lidl|fantastico|фантастико)\b",
    re.I,
)


def flyer_offers(lines, bounds, render_crop, store):
    """Extract price/name pairs from the same region of a brochure page."""
    tag_lines = [(box, text) for box, text in lines if PRICE.search(text)]
    offers = []
    for price_box, price_text in tag_lines:
        amounts = PRICE.findall(price_text)
        if len(amounts) == 2:
            euro = [value for value in amounts if value[1].lower() in {"€", "eur"}]
            if len(euro) == 1:
                amounts = euro
        if len(amounts) != 1:
            continue
        amount, currency = amounts[0]
        currency = "лв" if currency.lower().startswith("лв") else "€"
        center = (price_box.x0 + price_box.x1) / 2
        left = max(bounds.x0, center - bounds.width * 0.22)
        right = min(bounds.x1, center + bounds.width * 0.22)
        top = max(bounds.y0, price_box.y0 - bounds.height * 0.24)
        for other, _ in tag_lines:
            other_center = (other.x0 + other.x1) / 2
            if abs(other.y0 - price_box.y0) <= bounds.height * 0.07:
                midpoint = (center + other_center) / 2
                if other.x1 <= price_box.x0:
                    left = max(left, midpoint)
                elif other.x0 >= price_box.x1:
                    right = min(right, midpoint)
            elif top < other.y1 < price_box.y0 and left < other_center < right:
                top = max(top, other.y1)

        region = pymupdf.Rect(
            left, top, right, min(bounds.y1, price_box.y1 + bounds.height * 0.02)
        )
        best_name = ""
        name_box = None
        best_score = float("inf")
        discount = DISCOUNT.search(price_text)
        for box, name in lines:
            box_center = (box.x0 + box.x1) / 2
            if not (
                region.x0 <= box_center <= region.x1
                and region.y0 <= box.y0 <= box.y1 <= region.y1
            ):
                continue
            if discount is None:
                discount = DISCOUNT.search(name)
            if box.y1 > price_box.y0 or PRICE.search(name) or OFFER_COPY.search(name):
                continue
            name = name.strip(" ,-")
            letters = sum(char.isalpha() for char in name)
            if letters < 4 or len(name) > 85 or re.search(r"[%€]|^\d", name):
                continue
            score = (price_box.y0 - box.y1) / bounds.height + abs(
                ((box.x0 + box.x1) / 2) - center
            ) / bounds.width * 0.25
            if score < best_score:
                best_name, name_box, best_score = name, box, score

        if best_name:
            offers.append(
                {
                    "name": best_name,
                    "price": f"{amount.replace('.', ',')} {currency}",
                    "image_url": render_crop(region | name_box),
                    "store": store,
                    "discount_percent": int(discount.group(1)) if discount else None,
                }
            )
    return offers


def best_flyer_offers(offers, limit=40):
    ranked = sorted(
        offers, key=lambda offer: offer["discount_percent"] or 0, reverse=True
    )
    unique = {}
    for offer in ranked:
        key = (offer["name"].casefold(), offer["price"])
        unique.setdefault(key, offer)
    return list(unique.values())[:limit]


def jpeg_data_url(content):
    return "data:image/jpeg;base64," + base64.b64encode(content).decode("ascii")


def pdf_lines(page):
    lines = []
    for block in page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]:
        for line in block.get("lines", []):
            spans = line["spans"]
            value = " ".join(span["text"].strip() for span in spans).strip()
            if value:
                lines.append((pymupdf.Rect(line["bbox"]), value))
    return lines


def lidl_pdf_offers(content):
    offers = []
    with pymupdf.open(stream=content, filetype="pdf") as document:
        for page in document.pages(stop=12):

            def render_crop(region):
                scale = min(2, 500 / max(region.width, region.height))
                image = page.get_pixmap(
                    matrix=pymupdf.Matrix(scale, scale), clip=region
                )
                return jpeg_data_url(image.tobytes("jpeg", jpg_quality=82))

            offers.extend(flyer_offers(pdf_lines(page), page.rect, render_crop, "Lidl"))
    return best_flyer_offers(offers)


def lidl_flyer_is_current(identifier, today):
    dates = re.match(r"^(\d{2})-(\d{2})-(\d{2})-(\d{2})(?:-|$)", identifier)
    if dates is None:
        return True

    start_day, start_month, end_day, end_month = map(int, dates.groups())
    try:
        for start_year in (today.year - 1, today.year):
            start = date(start_year, start_month, start_day)
            end_year = start_year + ((end_month, end_day) < (start_month, start_day))
            end = date(end_year, end_month, end_day)
            if start <= today <= end:
                return True
    except ValueError:
        # Other identifiers may use a similar-looking numeric prefix.
        return True
    return False


def scrape_lidl():
    cache_key = "scraped_deals_lidl"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        listing = requests.get(
            "https://www.lidl.bg/c/broshura/s10020060", headers=HEADERS, timeout=10
        )
        listing.raise_for_status()
    except (requests.RequestException, RuntimeError):
        logger.warning("Could not load Lidl's brochure listing", exc_info=True)
        return []

    identifiers = re.findall(
        r"/(?:l/)?bg/broshura/([^/]+)/(?:view/flyer/page/\d+|ar/\d+)", listing.text
    )
    if not identifiers:
        identifiers = re.findall(r"\b\d{2}-\d{2}-\d{2}-\d{2}\b", listing.text)
    identifiers = list(
        dict.fromkeys(
            identifier
            for identifier in identifiers
            if identifier not in {"koshnica", "-6ade6a"}
        )
    )
    today = datetime.now(ZoneInfo("Europe/Sofia")).date()
    current_ids = [
        identifier
        for identifier in identifiers
        if lidl_flyer_is_current(identifier, today)
    ]
    deadline = monotonic() + 40
    for identifier in current_ids[:3]:
        if monotonic() >= deadline:
            break
        try:
            leaflet = requests.get(
                "https://endpoints.leaflets.schwarz/v4/flyer",
                params={
                    "flyer_identifier": identifier,
                    "region_id": 0,
                    "region_code": 0,
                },
                headers=HEADERS,
                timeout=10,
            )
            leaflet.raise_for_status()
            pdf_url = leaflet.json().get("flyer", {}).get("pdfUrl")
            if not pdf_url:
                continue
            pdf = requests.get(pdf_url, headers=HEADERS, timeout=25)
            pdf.raise_for_status()
            deals = lidl_pdf_offers(pdf.content)
        except (
            requests.RequestException,
            ValueError,
            RuntimeError,
            pymupdf.FileDataError,
        ):
            logger.warning("Could not read Lidl brochure %s", identifier, exc_info=True)
            continue
        if deals:
            cache.set(cache_key, deals, timeout=3600)
            return deals
    return []


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


def scrape_kaufland():
    cache_key = "scraped_deals_kaufland"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        response = requests.get(
            "https://www.kaufland.bg/aktualni-predlozheniya/oferti.html",
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
                        }
                    )
            deals = cards[:40]
        else:
            deals = []
            offer_data = data.get("props", {}).get("offerData", {})
            for cycle in offer_data.get("cycles", []):
                for category in cycle.get("categories", []):
                    for offer in category.get("offers", []):
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
                            deals.append(
                                {
                                    "name": name,
                                    "price": price,
                                    "image_url": absolute_image_url(
                                        offer.get("listImage")
                                        or (offer.get("detailImages") or [""])[0]
                                    ),
                                    "store": "Kaufland",
                                }
                            )
                        if len(deals) >= 40:
                            break
                    if len(deals) >= 40:
                        break
                if len(deals) >= 40:
                    break
    except Exception:
        deals = []

    cache.set(cache_key, deals, timeout=60 * 60)
    return deals


def recognize_flyer_lines(image):
    with io.BytesIO() as encoded:
        image.save(encoded, format="PNG")
        result = subprocess.run(
            [
                "tesseract",
                "stdin",
                "stdout",
                "-l",
                "bul+eng",
                "--psm",
                "11",
                "-c",
                "tessedit_create_tsv=1",
            ],
            input=encoded.getvalue(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=12,
            check=True,
        )

    if b"Failed loading language 'bul'" in result.stderr:
        raise subprocess.CalledProcessError(1, result.args, stderr=result.stderr)

    words_by_line = defaultdict(list)
    rows = csv.DictReader(io.StringIO(result.stdout.decode("utf-8")), delimiter="\t")
    for row in rows:
        word = row["text"]
        if not word or float(row["conf"]) < 45:
            continue
        x, y, width, height = (
            int(row[key]) for key in ("left", "top", "width", "height")
        )
        line_id = tuple(row[key] for key in ("block_num", "par_num", "line_num"))
        words_by_line[line_id].append((pymupdf.Rect(x, y, x + width, y + height), word))
    lines = []
    for words in words_by_line.values():
        rect = pymupdf.Rect(words[0][0])
        for box, _ in words[1:]:
            rect |= box
        text = " ".join(word for _, word in words)
        # The euro glyph on raster price tags can be recognized as E or Е.
        text = re.sub(r"(\d[,.]\d{2})\s+[EЕ](?=\s|$)", r"\1 €", text)
        lines.append((rect, text))
    return lines


def fantastico_page_offers(content):
    with Image.open(io.BytesIO(content)) as image:
        image = image.convert("RGB")

        def render_crop(region):
            crop = image.crop((region.x0, region.y0, region.x1, region.y1))
            crop.thumbnail((500, 500))
            with io.BytesIO() as encoded:
                crop.save(encoded, format="JPEG", quality=82)
                return jpeg_data_url(encoded.getvalue())

        return flyer_offers(
            recognize_flyer_lines(image),
            pymupdf.Rect(0, 0, image.width, image.height),
            render_crop,
            "Fantastico",
        )


def scrape_fantastico():
    cache_key = "scraped_deals_fantastico"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        listing = requests.get(
            "https://www.fantastico.bg/special-offers", headers=HEADERS, timeout=10
        )
        listing.raise_for_status()
        soup = BeautifulSoup(listing.text, "html.parser")
        selector = ".brochure-switch[data-url]"
        current = soup.select_one(f"{selector}.active") or soup.select_one(selector)
        if current is None:
            return []
        flipbook_url = urljoin(listing.url, current["data-url"])
        if urlsplit(flipbook_url).hostname != "online.flippingbook.com":
            return []
        flipbook = requests.get(
            flipbook_url, headers={**HEADERS, "Referer": listing.url}, timeout=10
        )
        flipbook.raise_for_status()

        policy_match = re.search(
            r"var initialPolicies\s*=\s*(\[.*?\]);", flipbook.text, re.S
        )
        content_match = re.search(r"ContentRoot:\s*['\"]([^'\"]+)['\"]", flipbook.text)
        if not policy_match or not content_match:
            return []
        content_root = urljoin(flipbook_url, content_match[1]).rstrip("/") + "/"
        content_parts = urlsplit(content_root)
        policy = next(
            (
                item
                for item in json.loads(policy_match[1])
                if urlsplit(item.get("PathPrefix", "")).path.rstrip("/")
                == content_parts.path.rstrip("/")
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
        count = re.search(r"TotalPages:\s*(\d+)", flipbook.text)
        page_count = min(int(count[1]), 12) if count else 12
    except (requests.RequestException, ValueError, KeyError):
        logger.warning("Could not load Fantastico's current brochure", exc_info=True)
        return []

    deals = []
    deadline = monotonic() + 40
    for page_number in range(1, page_count + 1):
        if monotonic() >= deadline:
            break
        suffix = f"common/pages/html5substrates/page{page_number:04d}_1.webp"
        try:
            page = requests.get(
                content_root + suffix,
                params=params,
                headers={**HEADERS, "Referer": flipbook_url},
                timeout=8,
            )
            page.raise_for_status()
            deals.extend(fantastico_page_offers(page.content))
        except (FileNotFoundError, subprocess.CalledProcessError):
            logger.warning(
                "Fantastico OCR requires Tesseract with Bulgarian data", exc_info=True
            )
            break
        except (requests.RequestException, subprocess.TimeoutExpired, OSError):
            logger.warning("Could not read Fantastico brochure page %s", page_number)

    deals = best_flyer_offers(deals)
    if deals:
        cache.set(cache_key, deals, timeout=3600)
    return deals


class LidlDealsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        return Response(scrape_lidl(), status=200)


class KauflandDealsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        return Response(scrape_kaufland(), status=200)


class FantasticoDealsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        return Response(scrape_fantastico(), status=200)
