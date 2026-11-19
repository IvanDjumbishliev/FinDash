import json
import re
import io
import base64

import requests
from bs4 import BeautifulSoup
from django.core.cache import cache
import pymupdf
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


def image_data_url(pixmap):
    return "data:image/png;base64," + base64.b64encode(pixmap.tobytes("png")).decode("ascii")


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
                    document = pymupdf.open(stream=pdf_response.content, filetype="pdf")
                    pdf_deals = []

                    for page_index in range(min(document.page_count, 12)):
                        page = document[page_index]
                        blocks = page.get_text("blocks")
                        price_blocks = []

                        for block in blocks:
                            x0, y0, x1, y1, text, *_ = block
                            for match in re.finditer(
                                r"(?<!\d)(\d+[,.]\d{2})\s*€",
                                text,
                                re.IGNORECASE,
                            ):
                                price_blocks.append(
                                    (float(y0), float(x0), float(x1), float(y1),
                                     match.group(1), text)
                                )

                        seen_names = set()
                        for price_y0, price_x0, price_x1, price_y1, price, price_text in price_blocks:
                            price_x_center = (price_x0 + price_x1) / 2
                            candidates = []
                            for name_x0, name_y0, name_x1, name_y1, name, *_ in blocks:
                                if name_y1 >= price_y0 or price_y0 - name_y1 > 180:
                                    continue
                                name_x_center = (name_x0 + name_x1) / 2
                                if abs(name_x_center - price_x_center) > 180:
                                    continue
                                clean = re.sub(r"\s+", " ", name).strip()
                                if len(clean) < 3:
                                    continue
                                if re.search(
                                    r"€|акция|цена|виж повече|lidl|опаковка|бр\.|kg|g\b|l\b",
                                    clean,
                                    re.IGNORECASE,
                                ):
                                    continue
                                if re.fullmatch(r"[\d%≈+\s.-]+", clean):
                                    continue
                                candidates.append(
                                    (name_y0, name_x0, clean)
                                )

                            candidates.sort(key=lambda item: (item[0], item[1]))
                            name = " ".join(
                                text for _, _, text in candidates[-4:]
                            )
                            name = re.sub(r"\s+", " ", name).strip(" ,-")
                            if len(name) < 3:
                                continue
                            noise_words = (
                                "до 50%",
                                "по-евтино",
                                "безплатно",
                                "акция",
                                "виж повече",
                                "lidl",
                                "сваляме",
                                "заслужава",
                                "от понеделник",
                                "от четвъртък",
                                "на 100 продукта",
                                "week",
                                "съвместна инициатива",
                                "гаранция за качество",
                                "качество",
                                "да се консумира",
                                "вкл.",
                                "вземи",
                                "пекарна",
                                "възраст",
                            )
                            if any(noise in name.lower() for noise in noise_words):
                                continue
                            if re.fullmatch(r"[\d%≈+\s.-]+", name):
                                continue
                            if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", name):
                                continue
                            key = (name.lower(), price)
                            if key in seen_names:
                                continue
                            seen_names.add(key)

                            left = max(0, price_x0 - 100)
                            top = max(0, (candidates[-1][0] - 10) if candidates else price_y0 - 80)
                            right = min(page.rect.width, price_x1 + 100)
                            bottom = min(page.rect.height, price_y1 + 20)
                            pix = page.get_pixmap(
                                matrix=pymupdf.Matrix(2, 2),
                                clip=pymupdf.Rect(left, top, right, bottom),
                                alpha=False,
                            )
                            crop_url = image_data_url(pix)

                            pdf_deals.append(
                                {
                                    "name": name,
                                    "price": f"{price} €",
                                    "image_url": crop_url,
                                    "store": "Lidl",
                                }
                            )
                            if len(pdf_deals) >= 40:
                                break
                        if len(pdf_deals) >= 40:
                            break

                    if pdf_deals:
                        deals = pdf_deals
                        break

                if not pdf_deals:
                    text_reader = PdfReader(io.BytesIO(pdf_response.content))
                    text_deals = []
                    for page_index, pdf_page in enumerate(text_reader.pages[:12]):
                        page_data = (
                            flyer.get("pages", [])[page_index]
                            if page_index < len(flyer.get("pages", []))
                            else {}
                        )
                        page_image = (
                            page_data.get("image")
                            or page_data.get("zoom")
                            or page_data.get("thumbnail")
                            or ""
                        )
                        text = pdf_page.extract_text() or ""
                        lines = [
                            re.sub(r"\s+", " ", line).strip()
                            for line in text.splitlines()
                            if line.strip()
                        ]
                        for line_index, line in enumerate(lines):
                            price_match = re.search(
                                r"(?<!\d)(\d+[,.]\d{2})\s*€",
                                line,
                                re.IGNORECASE,
                            )
                            if not price_match:
                                continue
                            candidates = []
                            for candidate in reversed(
                                lines[max(0, line_index - 8):line_index]
                            ):
                                if re.search(
                                    r"€|цена|акция|виж повече|lidl|опаковка|бр\.|kg|g\b|l\b|от понеделник|от четвъртък",
                                    candidate,
                                    re.IGNORECASE,
                                ):
                                    continue
                                if len(candidate) >= 3:
                                    candidates.append(candidate)
                                if len(candidates) == 4:
                                    break
                            name = " ".join(reversed(candidates)).strip()
                            name = re.sub(r"\s+", " ", name).strip(" ,-")
                            if len(name) < 3:
                                continue
                            name_lower = name.lower()
                            if any(
                                noise in name_lower
                                for noise in (
                                    "на 100 продукта",
                                    "сваляме",
                                    "заслужава",
                                    "виж повече",
                                    "акция",
                                    "безплатно",
                                )
                            ):
                                continue
                            try:
                                numeric_price = float(
                                    price_match.group(1).replace(",", ".")
                                )
                                if numeric_price <= 0 or numeric_price > 100:
                                    continue
                            except ValueError:
                                continue
                            key = (name.lower(), price_match.group(1))
                            if any(
                                existing["name"].lower() == key[0]
                                and existing["price"].startswith(key[1])
                                for existing in text_deals
                            ):
                                continue
                            text_deals.append(
                                {
                                    "name": name,
                                    "price": f"{price_match.group(1)} €",
                                    "image_url": page_image,
                                    "store": "Lidl",
                                }
                            )
                            if len(text_deals) >= 40:
                                break
                        if len(text_deals) >= 40:
                            break
                    if text_deals:
                        deals = text_deals
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
        flipbook_url = "https://online.flippingbook.com/view/883575965/"
        try:
            offers_page = requests.get(
                "https://www.fantastico.bg/special-offers",
                headers=HEADERS,
                timeout=20,
            )
            if offers_page.status_code == 200:
                soup = BeautifulSoup(offers_page.text, "html.parser")
                active_switch = soup.select_one(
                    "div.brochure-switch[data-url].active, "
                    "div.brochure-switch[data-url]"
                )
                if active_switch and active_switch.get("data-url"):
                    flipbook_url = active_switch["data-url"]
        except Exception:
            pass
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
            if ocr is not None:
                ocr_result, _ = ocr(page.content)
                if ocr_result:
                    from PIL import Image
                    from io import BytesIO

                    image = Image.open(BytesIO(page.content)).convert("RGB")
                    width, height = image.size
                    seen = set()

                    for box, text, score in ocr_result:
                        if score < 0.45:
                            continue
                        price_match = re.search(
                            r"(?<!\d)(\d{1,3}[,.]\d{1,2})",
                            text,
                        )
                        if not price_match:
                            continue

                        price = price_match.group(1).replace(".", ",")
                        box_x = [point[0] for point in box]
                        box_y = [point[1] for point in box]
                        price_x = sum(box_x) / 4
                        price_y = min(box_y)
                        name = "Фантастико оферта"

                        left = max(
                            0,
                            int(price_x - width * 0.28),
                        )
                        top = max(
                            0,
                            int(price_y - height * 0.16),
                        )
                        right = min(
                            width,
                            int(price_x + width * 0.28),
                        )
                        bottom = min(
                            height,
                            int(max(box_y) + height * 0.08),
                        )
                        crop = image.crop((left, top, right, bottom))
                        crop.thumbnail((500, 320))
                        encoded = io.BytesIO()
                        crop.save(encoded, format="JPEG", quality=82)
                        data_url = (
                            "data:image/jpeg;base64,"
                            + base64.b64encode(encoded.getvalue()).decode("ascii")
                        )

                        key = (name.lower(), price)
                        if key in seen:
                            continue
                        seen.add(key)
                        deals.append(
                            {
                                "name": name,
                                "price": f"{price} лв",
                                "image_url": data_url,
                                "store": "Fantastico",
                            }
                        )
                        if len(deals) >= 20:
                            break
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
