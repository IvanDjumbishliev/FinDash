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
        offers_page = requests.get(
            "https://www.fantastico.bg/special-offers",
            headers=HEADERS,
            timeout=20,
        )
        offers_page.raise_for_status()
        soup = BeautifulSoup(offers_page.text, "html.parser")
        active_switch = soup.select_one(
            "div.brochure-switch[data-url].active, div.brochure-switch[data-url]"
        )
        if active_switch is None:
            return []

        flipbook_url = (
            active_switch.get("data-url")
            or "https://online.flippingbook.com/view/883575965/"
        )
        flipbook = requests.get(
            flipbook_url,
            headers={
                **HEADERS,
                "Referer": "https://www.fantastico.bg/",
            },
            timeout=30,
        )
        flipbook.raise_for_status()

        policy_match = re.search(
            r"var initialPolicies\s*=\s*(\[.*?\]);",
            flipbook.text,
            re.S,
        )
        content_match = re.search(
            r"ContentRoot:\s*'([^']+)'",
            flipbook.text,
        )
        if not policy_match or not content_match:
            return []

        policies = json.loads(policy_match.group(1))
        content_root = content_match.group(1)
        policy = next(
            (
                item
                for item in policies
                if item.get("PathPrefix", "").rstrip("/").endswith(
                    content_root.split(".net", 1)[-1].rstrip("/")
                )
            ),
            None,
        )
        if policy is None:
            policy = next(
                (
                    item
                    for item in policies
                    if "00710E38" in item.get("PathPrefix", "")
                ),
                policies[0] if policies else None,
            )
        if policy is None:
            return []

        params = {
            "Key-Pair-Id": policy["KeyId"],
            "Policy": policy["Policy"],
            "Signature": policy["Signature"],
        }
        page_count_match = re.search(r"TotalPages:\s*(\d+)", flipbook.text)
        page_count = (
            int(page_count_match.group(1))
            if page_count_match
            else 40
        )

        try:
            from rapidocr_onnxruntime import RapidOCR

            ocr = RapidOCR()
        except Exception:
            return []

        deals = []
        for page_number in range(2, min(page_count + 1, 31)):
            suffix = (
                f"common/pages/html5substrates/"
                f"page{page_number:04d}_1.webp"
            )
            page = requests.get(
                content_root + suffix,
                params=params,
                headers={
                    **HEADERS,
                    "Referer": "https://online.flippingbook.com/",
                },
                timeout=20,
            )
            if page.status_code != 200:
                continue

            ocr_result, _ = ocr(page.content)
            if not ocr_result:
                continue

            recognized = [
                (text.strip(), score)
                for _, text, score in ocr_result
                if text and score >= 0.45
            ]
            price = ""
            name_parts = []
            for text, _ in recognized:
                price_match = re.search(
                    r"(?<!\d)(\d{1,3}(?:[,.]\d{1,2})?)",
                    text,
                )
                if price_match and (
                    "," in price_match.group(1)
                    or "." in price_match.group(1)
                ):
                    price = f"{price_match.group(1).replace('.', ',')} лв"
                    break

                clean = re.sub(r"[^A-Za-zА-Яа-я0-9&+%-]+", " ", text)
                clean = re.sub(r"\s+", " ", clean).strip()
                if len(clean) >= 3:
                    name_parts.append(clean)

            name = " ".join(dict.fromkeys(name_parts[:4])).strip()
            if not name:
                name = f"Фантастико актуална оферта, стр. {page_number}"

            signed_image = content_root + suffix
            signed_image += (
                "?" + requests.Request(
                    "GET",
                    signed_image,
                    params=params,
                ).prepare().url.split("?", 1)[-1]
            )
            deals.append(
                {
                    "name": name,
                    "price": price,
                    "image_url": signed_image,
                    "store": "Fantastico",
                }
            )
            if len(deals) >= 20:
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
