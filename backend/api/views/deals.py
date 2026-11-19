import json
import re

import requests
from bs4 import BeautifulSoup
from django.core.cache import cache
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


def scrape_lidl():
    cache_key = "scraped_deals_lidl"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        page = requests.get(
            "https://www.lidl.bg/c/broshura/s10020060",
            headers=HEADERS,
            timeout=20,
        )
        page.raise_for_status()

        identifiers = []
        for match in re.findall(
            r"/(?:l/)?bg/broshura/([^/]+)/(?:view/flyer/page/\d+|ar/\d+)",
            page.text,
        ):
            if match and match not in {"koshnica", "-6ade6a"}:
                identifiers.append(match)
        if not identifiers:
            identifiers = re.findall(r"\b\d{2}-\d{2}-\d{2}-\d{2}\b", page.text)
        identifiers = list(dict.fromkeys(identifiers))

        deals = []
        for identifier in identifiers[:3]:
            try:
                leaflet = requests.get(
                    "https://endpoints.leaflets.schwarz/v4/flyer",
                    params={
                        "flyer_identifier": identifier,
                        "region_id": 0,
                        "region_code": 0,
                    },
                    headers=HEADERS,
                    timeout=20,
                )
                leaflet.raise_for_status()
                flyer = leaflet.json().get("flyer", {})
                if not flyer:
                    continue

                for page_data in flyer.get("pages", []):
                    keywords = page_data.get("keyWords") or ""
                    alt_text = page_data.get("altText") or ""
                    image = (
                        page_data.get("image")
                        or page_data.get("zoom")
                        or page_data.get("thumbnail")
                        or ""
                    )

                    for price_match in re.finditer(
                        r"(?<!\d)([1-9]\d{0,2}(?:[,.]\d{1,2})?)\s*(€|лв|lev)",
                        keywords,
                        re.IGNORECASE,
                    ):
                        before = keywords[max(0, price_match.start() - 90):price_match.start()]
                        words = re.findall(
                            r"[A-Za-zА-Яа-я0-9][A-Za-zА-Яа-я0-9'’+&/.-]*",
                            before,
                        )
                        words = [
                            word
                            for word in words[-10:]
                            if len(word) > 1
                            and word.lower()
                            not in {
                                "продукта",
                                "цена",
                                "cena",
                                "проф",
                                "от",
                                "до",
                                "lidl",
                            }
                        ]
                        name = " ".join(words).strip(" ,-")
                        if not name:
                            name = alt_text.strip() or "Lidl weekly offer"
                        name = re.sub(r"\s+", " ", name).strip()
                        deals.append(
                            {
                                "name": name,
                                "price": f"{price_match.group(1)} {price_match.group(2)}",
                                "image_url": image,
                                "store": "Lidl",
                            }
                        )
                        if len(deals) >= 40:
                            break
                    if len(deals) >= 40:
                        break
            except Exception:
                continue
            if deals:
                break
    except Exception:
        deals = []

    cache.set(cache_key, deals, timeout=60 * 60)
    return deals


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
                    return json.loads(html[start:index + 1])
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
                            r"\s+", " ",
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
                            price = f"{price_value} €" if price_value is not None else ""
                        if name:
                            deals.append(
                                {
                                    "name": name,
                                    "price": price,
                                    "image_url": absolute_image_url(
                                        offer.get("listImage")
                                        or (
                                            offer.get("detailImages") or [""]
                                        )[0]
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


def scrape_fantastico():
    cache_key = "scraped_deals_fantastico"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        response = requests.get(
            "https://www.fantastico.bg/special-offers",
            headers=HEADERS,
            timeout=20,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        deals = []

        for switch in soup.select("div.brochure-switch[data-url]"):
            text = re.sub(
                r"\s+", " ",
                switch.get_text(" ", strip=True),
            ).strip()
            name = re.sub(
                r"\s*(Виж брошура)\s*$",
                "",
                text,
                flags=re.IGNORECASE,
            ).strip()
            if not name:
                name = "Fantastico brochure"

            period_match = re.search(
                r"(\d{2}[.]\d{2}[.]\d{4}).*?(до\s*)?(\d{2}[.]\d{2}[.]\d{4})",
                name,
                re.IGNORECASE,
            )
            price = ""
            if period_match:
                price = f"{period_match.group(1)} - {period_match.group(3)}"

            image = switch.select_one("img[src]")
            image_url = ""
            if image:
                image_url = absolute_image_url(
                    image.get("src") or image.get("data-src")
                )

            deals.append(
                {
                    "name": name,
                    "price": price,
                    "image_url": image_url,
                    "store": "Fantastico",
                }
            )
            if len(deals) >= 10:
                break
    except Exception:
        deals = []

    cache.set(cache_key, deals, timeout=60 * 60)
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
