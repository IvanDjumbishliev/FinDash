import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from api.models import Transaction

SYMBOLS = {"€": "EUR", "£": "GBP", "$": "USD", "лв": "BGN", "лв.": "BGN"}
CURRENCY_TOKEN = re.compile(r"(?:[A-Z]{3}|лв\.?|[€£$])", re.I)
MAX_ROWS = 2000
MAX_ERRORS = 20


class StatementError(Exception):
    def __init__(self, message, *, status=400, code=None):
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass(frozen=True)
class ParsedStatement:
    rows: list
    errors: list
    columns: tuple = ()
    mapping: dict | None = None
    needs_mapping: bool = False


def currency_code(value):
    value = str(value or "").strip()
    if re.fullmatch(r"[A-Za-z]{3}", value):
        return value.upper()
    if code := SYMBOLS.get(value.casefold()):
        return code
    raise ValueError("Provide a three-letter currency code or a supported currency symbol.")


def normalize_date(value, order):
    value = str(value).strip()
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?:[ T].+)?", value):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            parsed = None
    else:
        parsed = None
        first, second = ("%d", "%m") if order == "DMY" else ("%m", "%d")
        for separator in (".", "/", "-"):
            try:
                parsed = datetime.strptime(value, f"{first}{separator}{second}{separator}%Y")
                break
            except ValueError:
                continue
    if parsed is None:
        raise ValueError("Enter a valid transaction date in the selected date format.")
    return (timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed).isoformat()


def direction_sign(value):
    token = str(value).strip().casefold()
    if token in {"debit", "dr", "d", "out", "withdrawal", "дебит"}:
        return -1
    if token in {"credit", "cr", "c", "in", "deposit", "кредит"}:
        return 1
    raise ValueError("Use a debit or credit indicator.")


def parse_amount(value):
    text = str(value).strip().replace("−", "-").replace("’", "'")
    indicator = re.search(r"\s*(CR|DR)$", text, re.I)
    sign = direction_sign(indicator[1]) if indicator else None
    if indicator:
        text = text[:indicator.start()].strip()
    if sign is None and (text.startswith("(") and text.endswith(")")):
        sign, text = -1, text[1:-1].strip()
    if text[:1] in ("-", "+") or text.endswith("-"):
        symbol = text[0] if text[:1] in ("-", "+") else text[-1]
        explicit = -1 if symbol == "-" else 1
        if sign is not None and sign != explicit:
            raise ValueError("The amount has conflicting debit and credit signs.")
        sign = explicit
        text = (text[1:] if text[:1] in ("-", "+") else text[:-1]).strip()

    currency = None
    match = re.match(CURRENCY_TOKEN, text) or re.search(rf"{CURRENCY_TOKEN.pattern}$", text, re.I)
    if match:
        currency = currency_code(match[0])
        text = (text[:match.start()] + text[match.end():]).strip()
    if sign is None and text[:1] in ("-", "+"):
        sign = -1 if text[0] == "-" else 1
        text = text[1:].strip()

    text = re.sub(r"[\u00a0\u202f ]", " ", text)
    punctuation = [separator for separator in (",", ".") if separator in text]
    decimal_separator = max(punctuation, key=text.rfind) if punctuation else None
    fractional = ""
    whole = text
    if decimal_separator:
        before, after = text.rsplit(decimal_separator, 1)
        if re.fullmatch(r"[0-9]{1,2}", after):
            whole, fractional = before, after
    if not re.fullmatch(r"[0-9]+|[0-9]{1,3}(?P<g>[., '])[0-9]{3}(?:(?P=g)[0-9]{3})*", whole):
        raise ValueError("Use a valid amount with at most two decimal places.")
    if fractional and decimal_separator in whole:
        raise ValueError("Use different grouping and decimal separators.")
    digits = re.sub(r"[^0-9]", "", whole)
    amount = Decimal(f"{digits}.{fractional or '0'}")
    return amount * (sign or 1), currency


def normalize_row(fields, *, default_currency=None, date_order="DMY"):
    timestamp = normalize_date(fields.get("date", ""), date_order)
    description = str(fields.get("description") or "").strip()
    if not 1 <= len(description) <= 2000 or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", description):
        raise ValueError("Provide a valid transaction description (up to 2,000 characters).")

    detected_currency = None
    try:
        if "amount" in fields:
            amount, detected_currency = parse_amount(fields["amount"])
            if indicator := fields.get("direction"):
                sign = direction_sign(indicator)
                if sign == 1 and amount < 0:
                    raise ValueError("Credit direction conflicts with the negative amount.")
                amount = abs(amount) * sign
        else:
            debit, debit_currency = parse_amount(fields.get("debit") or "0")
            credit, credit_currency = parse_amount(fields.get("credit") or "0")
            if bool(debit) == bool(credit):
                raise ValueError("Provide exactly one non-zero debit or credit.")
            amount, detected_currency = (-abs(debit), debit_currency) if debit else (abs(credit), credit_currency)
        if not Decimal("0.01") <= abs(amount) <= Decimal("99999999.99"):
            raise ValueError("Transaction amount is zero or out of range.")
    except InvalidOperation as error:
        raise ValueError("Use a valid transaction amount.") from error

    currency = currency_code(fields["currency"]) if fields.get("currency") else detected_currency or default_currency
    if not currency:
        raise ValueError("Provide a transaction currency or select a default currency.")
    if detected_currency and detected_currency != currency:
        raise ValueError("The amount and currency column disagree.")
    category = str(fields.get("category") or Transaction.Category.GENERAL).strip().casefold()
    if category not in Transaction.Category.values:
        raise ValueError("Use a valid FinDash category or leave the category unmapped.")
    reference = str(fields.get("reference") or "").strip()
    if len(reference) > 128 or re.search(r"[\x00-\x1f]", reference):
        raise ValueError("Provide a valid transaction reference (up to 128 characters).")
    return {
        "timestamp": timestamp,
        "amount": format(amount, ".2f"),
        "currency": currency,
        "particulars": description,
        "category": category,
        "category_supplied": bool(fields.get("category")),
        "reference": reference,
        "merchant_hint": str(fields.get("merchant") or "").strip()[:255],
    }
