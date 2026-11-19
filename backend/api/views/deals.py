import json
import re
import io

import requests
from bs4 import BeautifulSoup
from django.core.cache import cache
from PyPDF2 import PdfReader
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

                pdf_url = flyer.get("pdfUrl")
                if pdf_url:
                    pdf_response = requests.get(
                        pdf_url,
                        headers=HEADERS,
                        timeout=60,
                    )
                    pdf_response.raise_for_status()
                    reader = PdfReader(io.BytesIO(pdf_response.content))

                    pdf_deals = []
                    for pdf_page_index, pdf_page in enumerate(reader.pages[:12]):
                        blocks = []

                        def visitor(text, cm, tm, font, size):
                            x = tm[4]
                            y = tm[5]
                            if text.strip():
                                blocks.append(
                                    (round(y, 1), round(x, 1), text.strip())
                                )

                        pdf_page.extract_text(visitor_text=visitor)

                        page_data = (
                            flyer.get("pages", [])[pdf_page_index]
                            if pdf_page_index < len(flyer.get("pages", []))
                            else {}
                        )
                        page_image = (
                            page_data.get("image")
                            or page_data.get("zoom")
                            or page_data.get("thumbnail")
                            or ""
                        )

                        column_groups = []
                        for column in sorted({round(x, -1) for _, x, _ in blocks}):
                            column_blocks = [
                                (y, x, text)
                                for y, x, text in blocks
                                if abs(x - column) <= 25
                            ]
                            if column_blocks:
                                column_groups.append(column_blocks)

                        for column_blocks in column_groups:
                            column_blocks.sort(key=lambda item: (-item[0], item[1]))
                            price_matches = []
                            for y, x, text in column_blocks:
                                match = re.search(
                                    r"(?<!\d)(\d+[,.]\d{2})\s*€",
                                    text,
                                )
                                if match:
                                    price_matches.append((y, x, match.group(1)))

                            for price_y, price_x, price in price_matches:
                                name_candidates = [
                                    text
                                    for y, x, text in column_blocks
                                    if 20 <= price_y - y <= 180
                                    and abs(x - price_x) <= 130
                                    and len(text) >= 3
                                    and not re.search(
                                        r"^\d|€|акция|цена|виж повече|lidl|опаковка|бр\.|kg|g\b|l\b",
                                        text,
                                        re.IGNORECASE,
                                    )
                                ]
                                name_candidates = [
                                    re.sub(r"\s+", " ", text).strip()
                                    for text in name_candidates
                                ]
                                name_candidates = list(dict.fromkeys(name_candidates))
                                name = " ".join(name_candidates[-4:])
                                name = re.sub(r"^[-–\s]+|[-–\s]+$", "", name)
                                if len(name) >= 3:
                                    noise_words = (
                                        "до 50%",
                                        "по-евтино",
                                        "безплатно",
                                        "акция",
                                        "виж повече",
                                        "lidl",
                                        "сваляме",
                                        "умерено от лица",
                                    )
                                    if any(
                                        noise in name.lower()
                                        for noise in noise_words
                                    ):
                                        continue
                                    if re.fullmatch(r"[\d%≈+\s.-]+", name):
                                        continue
                                    if "/uni" in name.lower():
                                        continue
                                    normalized_price = re.sub(
                                        r"\s*[€лв]\s*", "",
                                        price,
                                    ).replace(",", ".")
                                    deal_key = (name.lower(), normalized_price)
                                    if deal_key in {
                                        (
                                            deal["name"].lower(),
                                            re.sub(
                                                r"\s*[€лв]\s*",
                                                "",
                                                deal["price"],
                                            ).replace(",", "."),
                                        )
                                        for deal in pdf_deals
                                    }:
                                        continue
                                    pdf_deals.append(
                                        {
                                            "name": name,
                                            "price": f"{price} €",
                                            "image_url": page_image,
                                            "store": "Lidl",
                                        }
                                    )
                                if len(pdf_deals) >= 40:
                                    break
                            if len(pdf_deals) >= 40:
                                break
                        if len(pdf_deals) >= 40:
                            break

                    if pdf_deals:
                        deals = pdf_deals
                        break

                for page_data in flyer.get("pages", []):
                    image = (
                        page_data.get("image")
                        or page_data.get("zoom")
                        or page_data.get("thumbnail")
                        or ""
                    )
                    page_number = page_data.get("number")
                    if image:
                        deals.append(
                            {
                                "name": (
                                    f"Lidl weekly offer - page {page_number}"
                                    if page_number
                                    else "Lidl weekly offer"
                                ),
                                "price": "",
                                "image_url": image,
                                "store": "Lidl",
                            }
                        )
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

        deals = []
        try:
            from rapidocr_onnxruntime import RapidOCR

            ocr = RapidOCR()
        except Exception:
            ocr = None

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

            signed_image = content_root + suffix
            signed_image += (
                "?" + requests.Request(
                    "GET",
                    signed_image,
                    params=params,
                ).prepare().url.split("?", 1)[-1]
            )
            name = f"Фантастико оферта - страница {page_number}"
            price = ""
            if ocr is not None:
                ocr_result, _ = ocr(page.content)
                name_parts = []
                if ocr_result:
                    for _, text, score in ocr_result:
                        if score < 0.45:
                            continue
                        price_match = re.search(
                            r"(?<!\d)(\d{1,3}(?:[,.]\d{1,2})?)",
                            text,
                        )
                        if price_match and (
                            "," in price_match.group(1)
                            or "." in price_match.group(1)
                        ):
                            price = f"{price_match.group(1).replace('.', ',')} лв"
                            continue
                        clean = re.sub(
                            r"[^A-Za-zА-Яа-я0-9&+%-]+",
                            " ",
                            text,
                        )
                        clean = re.sub(r"\s+", " ", clean).strip()
                        noise = (
                            "google",
                            "appstore",
                            "play",
                            "kaye",
                            "точка",
                        )
                        if len(clean) >= 4 and not any(
                            item in clean.lower() for item in noise
                        ):
                            name_parts.append(clean)
                name_parts = list(dict.fromkeys(name_parts))
                if name_parts:
                    name = " ".join(name_parts[:5]).strip()
                    if len(name) > 120:
                        name = name[:117].rstrip() + "..."
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
