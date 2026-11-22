"""Local receipt OCR and conservative extraction of values for user review."""
import hashlib
import io
import json
import os
import re
import subprocess
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageOps, UnidentifiedImageError

from api.services.grocery_catalog import normalized
from api.services.grocery_matching import classify
from api.services.statements.intelligence import merchant_identity, reference_identity
from api.services.statements.normalization import parse_amount

MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 16_000_000
MAX_ITEMS = 200
SOFIA = ZoneInfo("Europe/Sofia")
IMAGE_TYPES = {".jpg": ("JPEG", "image/jpeg"), ".jpeg": ("JPEG", "image/jpeg"),
               ".png": ("PNG", "image/png"), ".webp": ("WEBP", "image/webp")}
CURRENCY = re.compile(r"(?<!\w)(?:EUR|BGN|лв\.?|лева|евро)(?!\w)|€", re.I)
AMOUNT = re.compile(r"(?<!\S)([+−-]?(?:\d{1,3}(?:[ .,'\u00a0]\d{3})+|\d+)[,.]\d{2}-?)\s*(?:EUR|BGN|лв\.?|лева|евро|€)?\s*(?:[АБAB])?\s*$", re.I)
DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2}|\d{2}[./-]\d{2}[./-]\d{4})(?:[ T]+(\d{2}:\d{2}(?::\d{2})?))?\b")
QUANTITY = re.compile(r"^(\d+(?:[,.]\d{1,6})?)\s*(kg|кг|g|гр\.?|г|ml|мл|l|л|pcs?|бр\.?)?\s*[xх×]\s*([0-9]+[,.]\d{2,4})\s+(.+)$", re.I)
UNITS = {"кг": ("kg", 1), "kg": ("kg", 1), "г": ("kg", 1000), "гр": ("kg", 1000), "g": ("kg", 1000),
         "мл": ("l", 1000), "ml": ("l", 1000), "л": ("l", 1), "l": ("l", 1)}
LABELS = {
    "subtotal": r"subtotal|sub total|междинна сума|сума без ддс",
    "discounts": r"total discount|discounts?|отстъпка|отстъпки|обща отстъпка|намаление",
    "tax_total": r"vat total|total tax|vat|tax|ддс|общо ддс",
    "total": r"(?:grand )?total(?: due)?|amount due|общо(?: сума)?|крайна сума|сума за плащане|за плащане|всичко",
}
NON_PRODUCT = re.compile(r"^(?:cash|card|change|payment|visa|mastercard|платено|плащане|карта|в брой|вброй|ресто|касиер|бонус)\b", re.I)
REFERENCE = re.compile(r"(?:receipt\s*(?:no\.?|#)|фискален бон\s*(?:№|#)|бон\s*№)\s*[:#]?\s*([\w/-]{2,64})", re.I)


class ReceiptScanError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def receipt_image(upload):
    expected = IMAGE_TYPES.get(Path(upload.name).suffix.lower())
    if not expected or upload.content_type not in {expected[1], "application/octet-stream"}:
        raise ReceiptScanError("Choose a JPEG, PNG or WebP image.", 415)
    image_data = upload.read(MAX_BYTES + 1)
    if len(image_data) > MAX_BYTES:
        raise ReceiptScanError("Receipt images must be 8 MB or smaller.", 413)
    try:
        with Image.open(io.BytesIO(image_data), formats=[expected[0]]) as image:
            if image.width * image.height > MAX_PIXELS or getattr(image, "n_frames", 1) != 1:
                raise ReceiptScanError("Choose a single image of up to 16 megapixels.")
            grayscale = ImageOps.exif_transpose(image).convert("L")
            grayscale.thumbnail((2200, 3200))
            output = io.BytesIO()
            grayscale.save(output, format="PNG")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError) as error:
        raise ReceiptScanError("The receipt image could not be decoded.", 415) from error
    return hashlib.sha256(image_data).hexdigest(), output.getvalue()


def recognize_receipt(image):
    try:
        result = subprocess.run(
            ["tesseract", "stdin", "stdout", "-l", "bul+eng", "--psm", "6"],
            input=image, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            check=True, timeout=18, env={**os.environ, "OMP_THREAD_LIMIT": "1"},
        )
    except subprocess.TimeoutExpired as error:
        raise ReceiptScanError("Receipt recognition timed out. Try a clearer or smaller image.", 422) from error
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReceiptScanError("Local receipt recognition is unavailable right now.", 503) from error
    return result.stdout.decode("utf-8", errors="replace")[:32_000]


def receipt_date(text, date_order):
    match = DATE.search(text)
    if not match:
        return None
    raw_date = match[1]
    if raw_date[4] == "-":
        date_format = "%Y-%m-%d"
    else:
        separator = raw_date[2]
        date_format = separator.join(("%d", "%m", "%Y") if date_order == "DMY" else ("%m", "%d", "%Y"))
    try:
        date = datetime.strptime(raw_date, date_format).date()
        time = datetime.fromisoformat(f"{date}T{match[2]}").time() if match[2] else datetime.min.time()
        return datetime.combine(date, time, tzinfo=SOFIA).isoformat()
    except ValueError:
        return None


def extract_receipt(text, date_order):
    lines = [" ".join(line.split())[:320] for line in text.splitlines() if line.strip()][:500]
    header = {"purchased_at": receipt_date(text, date_order)}
    references = REFERENCE.search(text)
    header["reference"] = references[1] if references else ""
    header["merchant"] = next((line[:255] for line in lines[:5]
                               if re.search(r"[A-Za-zА-Яа-я]", line) and not DATE.search(line)
                               and not AMOUNT.search(line) and not REFERENCE.search(line)), "")
    items = []
    total_currency = None
    line_discounts = Decimal("0")
    for line in lines:
        match = AMOUNT.search(line)
        if not match:
            continue
        label = line[:match.start()].strip(" :")
        prefix_currency = re.search(r"(?:\s|^)(EUR|BGN|лв\.?|лева|евро|€)$", label, re.I)
        if prefix_currency:
            label = label[:prefix_currency.start()].strip(" :")
        if not label or not re.search(r"[A-Za-zА-Яа-я]", label):
            continue
        try:
            amount, _ = parse_amount(match[1])
        except ValueError:
            continue
        if abs(amount) > Decimal("9999999999.99"):
            continue
        field = next((key for key, pattern in LABELS.items() if re.fullmatch(pattern, label, re.I)), None)
        if field:
            if field == "total" and field in header:
                continue
            if field == "total":
                token = CURRENCY.search(line[match.start():]) or prefix_currency
                total_currency = ("BGN" if token[0].casefold().startswith(("лв", "лев", "bgn")) else "EUR") if token else None
            if field == "discounts":
                if label.casefold() in {"discount", "отстъпка", "намаление"} and items:
                    item = items[-1]
                    item["discount"] = str(Decimal(item.get("discount", "0")) + abs(amount))
                    line_total = Decimal(item["line_total"])
                    item["line_total"] = str(line_total - abs(amount).copy_sign(line_total))
                if label.casefold() in {"total discount", "обща отстъпка", "discounts", "отстъпки"}:
                    header[field] = str(abs(amount))
                else:
                    line_discounts += abs(amount)
            else:
                header[field] = str(amount)
            continue
        if "total" in header or NON_PRODUCT.match(label) or DATE.search(label) or len(items) >= MAX_ITEMS:
            continue
        quantity = unit_price = None
        unit = ""
        name = label
        if match_quantity := QUANTITY.fullmatch(label):
            raw_quantity, raw_unit, raw_price, name = match_quantity.groups()
            unit, scale = UNITS.get((raw_unit or "").lower().rstrip("."), ("item", 1))
            quantity = str((Decimal(raw_quantity.replace(",", ".")) / scale).quantize(Decimal("0.000001")))
            unit_price = str(Decimal(raw_price.replace(",", ".")) * scale)
        name = name[:255]
        category, _, _ = classify(normalized(name), "")
        items.append({
            "original_description": name, "normalized_name": normalized(name)[:255],
            "quantity": quantity, "unit": unit, "unit_price": unit_price, "line_total": str(amount),
            "category": category, "confidence": "0.65" if quantity is not None else "0.55",
        })
    if line_discounts and "discounts" not in header:
        header["discounts"] = str(line_discounts)
    currencies = {"BGN" if match[0].casefold().startswith(("лв", "лев", "bgn")) else "EUR"
                  for match in CURRENCY.finditer(text)}
    header["currency"] = total_currency or (next(iter(currencies)) if len(currencies) == 1 else None)
    warnings = []
    if not header["currency"]:
        warnings.append("Choose the original currency from the receipt.")
    if not header["purchased_at"]:
        warnings.append("Enter the purchase date and time.")
    if "total" not in header:
        warnings.append("Enter the printed final total.")
    if not items:
        warnings.append("No item rows were recognized. Add the items during review.")
    return {**header, "items": items, "warnings": warnings}


def receipt_fingerprint(data, items):
    merchant, identity = merchant_identity(data["merchant"])
    identity = identity or normalized(merchant)
    reference = reference_identity(data.get("reference", ""))
    purchased_at = data["purchased_at"].astimezone(SOFIA)
    components = [identity, data["currency"], format(data["total"], ".2f")]
    if reference:
        components.extend([purchased_at.date().isoformat(), reference])
    else:
        components.extend([purchased_at.isoformat(), sorted(
            (normalized(item["original_description"]), format(item["line_total"], ".2f")) for item in items
        )])
    digest = hashlib.sha256(json.dumps(components, ensure_ascii=False).encode()).hexdigest()
    return identity[:255], digest
