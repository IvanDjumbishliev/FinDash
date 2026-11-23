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
from pydantic import ValidationError

from api.services.grocery_catalog import normalized
from api.services.receipt_ai import suggest_receipt_evidence
from api.services.receipt_schema import MAX_ITEMS, ExtractedReceipt
from api.services.grocery_matching import classify
from api.services.statements.intelligence import merchant_identity, reference_identity
from api.services.statements.normalization import parse_amount

MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 16_000_000
MAX_IMAGES = 3
MAX_OCR_CHARACTERS = 32_000
SOFIA = ZoneInfo("Europe/Sofia")
IMAGE_TYPES = {".jpg": ("JPEG", "image/jpeg"), ".jpeg": ("JPEG", "image/jpeg"),
               ".png": ("PNG", "image/png"), ".webp": ("WEBP", "image/webp")}
HEIF_TYPES = {
    ".heic": {"image/heic", "image/heif"},
    ".heif": {"image/heif", "image/heic"},
}
MONEY_LIMIT = Decimal("9999999999.99")
ABBREVIATIONS = {"кис мл": "кисело мляко", "пр мл": "прясно мляко", "кр масл": "краве масло"}
METADATA = re.compile(r"^(?:receipt|fiscal receipt|фискален бон|касов бон|касова бележка|eik|еик|булстат|tax id|vat no|terminal|терминал)\b", re.I)
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
    extension = Path(upload.name).suffix.lower()
    content_type = (upload.content_type or "").lower()
    if extension in HEIF_TYPES:
        if content_type not in HEIF_TYPES[extension] | {"application/octet-stream"}:
            raise ReceiptScanError("The declared file type does not match the image extension.", 415)
        try:
            from pillow_heif import register_heif_opener
        except ImportError as error:
            raise ReceiptScanError("HEIC is unavailable on this server. Convert the image to JPEG or PNG.", 415) from error
        register_heif_opener(thumbnails=False, depth_images=False)
        image_format = "HEIF"
    else:
        expected = IMAGE_TYPES.get(extension)
        if not expected or content_type not in {expected[1], "application/octet-stream"}:
            raise ReceiptScanError("Choose a JPEG, PNG, WebP or supported HEIC image.", 415)
        image_format = expected[0]
    image_data = upload.read(MAX_BYTES + 1)
    if len(image_data) > MAX_BYTES:
        raise ReceiptScanError("Receipt images must be 8 MB or smaller.", 413)
    try:
        with Image.open(io.BytesIO(image_data), formats=[image_format]) as image:
            if image.width * image.height > MAX_PIXELS or getattr(image, "n_frames", 1) != 1:
                raise ReceiptScanError("Choose a single image of up to 16 megapixels.")
            oriented = ImageOps.exif_transpose(image)
            if "A" in oriented.getbands() or "transparency" in oriented.info:
                rgba = oriented.convert("RGBA")
                oriented = Image.new("RGB", rgba.size, "white")
                oriented.paste(rgba, mask=rgba.getchannel("A"))
            grayscale = oriented.convert("L")
            grayscale.thumbnail((2200, 3200))
            grayscale = ImageOps.autocontrast(grayscale, cutoff=0.5)
            output = io.BytesIO()
            grayscale.info.clear()
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
    return result.stdout.decode("utf-8", errors="replace")[:MAX_OCR_CHARACTERS]


def receipt_date(text, date_order):
    match = DATE.search(text)
    if not match:
        return None, None
    raw_date = match[1]
    if raw_date[4] == "-":
        date_format = "%Y-%m-%d"
    else:
        separator = raw_date[2]
        date_format = separator.join(("%d", "%m", "%Y") if date_order == "DMY" else ("%m", "%d", "%Y"))
    try:
        date = datetime.strptime(raw_date, date_format).date()
        if not match[2]:
            return date.isoformat(), None
        time = datetime.fromisoformat(f"{date}T{match[2]}").time()
        return date.isoformat(), datetime.combine(date, time, tzinfo=SOFIA).isoformat()
    except ValueError:
        return None, None



def clean_lines(text):
    return [" ".join(line.split())[:320] for line in text.splitlines() if line.strip()][:500]


def product_identity(name):
    identity = normalized(name)
    for abbreviation, expanded in ABBREVIATIONS.items():
        identity = re.sub(rf"(?<!\w){abbreviation}(?!\w)", expanded, identity)
    return identity[:255]


def product_label(line):
    return (bool(re.search(r"[A-Za-zА-Яа-я]", line)) and not any(
        regex.search(line) for regex in (DATE, REFERENCE, METADATA, NON_PRODUCT)
    ) and not any(re.fullmatch(pattern, line, re.I) for pattern in LABELS.values()))


def evidence_lines(lines, evidence):
    """Join adjacent description/amount lines only when both exist in local OCR."""
    working = lines.copy()
    for item in evidence.items:
        desc, price = item.description_line, item.amount_line
        if not 0 <= desc < price < len(lines) or price != desc + 1:
            continue
        if not product_label(lines[desc]) or AMOUNT.search(lines[desc]) or not AMOUNT.fullmatch(lines[price]):
            continue
        if desc < 5 and desc == next((index for index, row in enumerate(lines[:5]) if product_label(row)), None):
            continue
        working[desc] = f"{lines[desc]} {lines[price]}"
        working[price] = ""
    return working


def totals_check(items, total):
    if total is None or not items:
        return {"status": "insufficient_data"}
    item_total = sum((Decimal(item["line_total"]) for item in items), Decimal("0"))
    difference = Decimal(total) - item_total
    return {
        "item_total": item_total if abs(item_total) <= MONEY_LIMIT else None,
        "difference": difference if abs(difference) <= MONEY_LIMIT else None,
        "status": "matches" if difference == 0 else "mismatch",
    }


def extract_receipt(text, date_order, *, evidence=None, extra_warnings=()):
    original_lines = clean_lines(text)
    lines = evidence_lines(original_lines, evidence) if evidence else original_lines
    purchase_date, purchased_at = receipt_date(text, date_order)
    header = {"purchase_date": purchase_date, "purchased_at": purchased_at}
    references = REFERENCE.search(text)
    header["reference"] = references[1] if references else ""
    merchant_lines = {index: line for index, line in enumerate(original_lines[:5])
                      if product_label(line) and not AMOUNT.search(line)}
    header["merchant"] = merchant_lines.get(evidence.merchant_line) if evidence else None
    header["merchant"] = header["merchant"] or next(iter(merchant_lines.values()), None)
    items = []
    total_currency = None
    line_discounts = Decimal("0")
    warnings = list(extra_warnings)
    for line in lines:
        match = AMOUNT.search(line)
        if not match:
            continue
        label = line[:match.start()].strip(" :")
        prefix_currency = re.search(r"(?:\s|:|^)(EUR|BGN|лв\.?|лева|евро|€)$", label, re.I)
        if prefix_currency:
            label = label[:prefix_currency.start()].strip(" :")
        if not label or not re.search(r"[A-Za-zА-Яа-я]", label):
            continue
        try:
            amount, _ = parse_amount(match[1])
        except ValueError:
            continue
        if abs(amount) > MONEY_LIMIT:
            continue
        field = next((key for key, pattern in LABELS.items() if re.fullmatch(pattern, label, re.I)), None)
        if field:
            if field == "total" and field in header:
                if Decimal(header[field]) != amount:
                    warnings.append("Multiple final totals were found. Verify the pages and the printed total.")
                continue
            if field == "total":
                token = CURRENCY.search(line[match.start():]) or prefix_currency
                total_currency = ("BGN" if token[0].casefold().startswith(("лв", "лев", "bgn")) else "EUR") if token else None
            if field == "discounts":
                if label.casefold() in {"discount", "отстъпка", "намаление"} and items:
                    item = items[-1]
                    discount = Decimal(item.get("discount") or "0") + abs(amount)
                    line_total = Decimal(item["line_total"]) - abs(amount).copy_sign(Decimal(item["line_total"]))
                    if discount <= MONEY_LIMIT and abs(line_total) <= MONEY_LIMIT:
                        item["discount"] = str(discount)
                        item["line_total"] = str(line_total)
                if label.casefold() in {"total discount", "обща отстъпка", "discounts", "отстъпки"}:
                    header[field] = str(abs(amount))
                else:
                    line_discounts += abs(amount)
            else:
                header[field] = str(amount)
            continue
        if "total" in header or not product_label(label) or len(items) >= MAX_ITEMS:
            continue
        quantity = unit_price = None
        unit = ""
        name = label
        if match_quantity := QUANTITY.fullmatch(label):
            raw_quantity, raw_unit, raw_price, name = match_quantity.groups()
            unit, scale = UNITS.get((raw_unit or "").lower().rstrip("."), ("item", 1))
            parsed_quantity = Decimal(raw_quantity.replace(",", ".")) / scale
            parsed_price = Decimal(raw_price.replace(",", ".")) * scale
            if 0 < parsed_quantity < Decimal("1e8") and parsed_quantity == parsed_quantity.quantize(Decimal("0.000001")):
                quantity = str(parsed_quantity)
                if parsed_price < Decimal("1e10"):
                    unit_price = str(parsed_price)
            else:
                unit = ""
        name = name[:255]
        identity = product_identity(name)
        category, _, _ = classify(identity, "")
        items.append({
            "original_description": name, "normalized_name": identity,
            "quantity": quantity, "unit": unit, "unit_price": unit_price, "line_total": str(amount),
            "category": category, "confidence": "0.65" if quantity is not None else "0.55",
        })
    if 0 < line_discounts <= MONEY_LIMIT and "discounts" not in header:
        header["discounts"] = str(line_discounts)
    currencies = {"BGN" if match[0].casefold().startswith(("лв", "лев", "bgn")) else "EUR"
                  for match in CURRENCY.finditer(text)}
    header["currency"] = total_currency or (next(iter(currencies)) if len(currencies) == 1 else None)
    if not header["merchant"]:
        warnings.append("Enter the merchant name printed on the receipt.")
    if not header["currency"]:
        warnings.append("Choose the original currency from the receipt.")
    if not header["purchased_at"]:
        warnings.append("Enter the purchase date and time.")
    if "total" not in header:
        warnings.append("Enter the printed final total.")
    if not items:
        warnings.append("No item rows were recognized. Add the items during review.")
    check = totals_check(items, header.get("total"))
    if check["status"] == "mismatch":
        warnings.append("Item totals differ from the printed total. Review missing items, tax and discounts.")
    if len(items) == MAX_ITEMS:
        warnings.append("The item limit was reached. Check for missing lines.")
    return ExtractedReceipt.model_validate({
        **header, "items": items, "warnings": list(dict.fromkeys(warnings)), "totals_check": check,
    }).model_dump(mode="json", exclude_none=False)


def prepare_receipt_images(uploads):
    prepared = [receipt_image(upload) for upload in uploads]
    digests = list(dict.fromkeys(digest for digest, _ in prepared))
    pages = list(dict(prepared).values())
    digest = digests[0] if len(digests) == 1 else hashlib.sha256("".join(digests).encode()).hexdigest()
    return digest, pages


def scan_receipt(pages, *, date_order, consent=False):
    lines = []
    warnings = []
    for page in pages:
        current = clean_lines(recognize_receipt(page))
        overlap = next((size for size in range(min(20, len(lines), len(current)), 1, -1)
                        if lines[-size:] == current[:size] and len(set(current[:size])) > 1), 0)
        if overlap:
            warnings.append("Repeated lines at a page boundary were merged. Check that all items are present.")
        if not current:
            warnings.append("One or more images had no readable text. Retake those photos or enter missing items.")
        lines.extend(current[overlap:])
    if not lines:
        raise ReceiptScanError("No text was recognized. Retake the receipt in good light, with all text in focus.", 422)
    text = "\n".join(lines)[:MAX_OCR_CHARACTERS]
    lines = clean_lines(text)
    # Keep line positions stable while omitting payment, identifier and date lines.
    ai_lines = [None if any(pattern.search(line) for pattern in (NON_PRODUCT, METADATA, REFERENCE, DATE))
                or re.search(r"\b(?:[0-9][ -]?){12,19}\b", line) else line for line in lines]
    evidence, status = suggest_receipt_evidence(ai_lines, consent=consent)
    try:
        result = extract_receipt(text, date_order, evidence=evidence, extra_warnings=warnings)
    except ValidationError as error:
        raise ReceiptScanError("The receipt could not be read reliably. Try a clearer photo or a smaller section.", 422) from error
    return result, status


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
