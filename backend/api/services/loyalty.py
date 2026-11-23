"""Validate identifiers and barcode formats without changing encoded data."""
import re

MEMBERSHIP_ID = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9 _-]{0,62}[A-Za-z0-9])?")
GS1_LENGTHS = {"ean13": 13, "ean8": 8, "upca": 12}


def resembles_payment_card(identifier):
    digits = identifier.replace(" ", "").replace("-", "")
    if not re.fullmatch(r"[0-9]{13,19}", digits):
        return False
    total = 0
    for index, digit in enumerate(reversed(digits)):
        value = int(digit) * (2 if index % 2 else 1)
        total += value - 9 if value > 9 else value
    return total % 10 == 0


def valid_gs1_identifier(identifier, code_format):
    length = GS1_LENGTHS.get(code_format)
    if length is None:
        return True
    if len(identifier) != length or not re.fullmatch(r"[0-9]+", identifier):
        return False
    total = sum(int(digit) * (3 if index % 2 == 0 else 1)
                for index, digit in enumerate(reversed(identifier[:-1])))
    return (total + int(identifier[-1])) % 10 == 0
