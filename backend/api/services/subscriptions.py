import re
import unicodedata
from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from difflib import SequenceMatcher
from statistics import median

from django.utils import timezone

from api.models import Subscription, Transaction

FREQUENCIES = {
    Subscription.Frequency.WEEKLY: (0, 1),
    Subscription.Frequency.MONTHLY: (1, 4),
    Subscription.Frequency.QUARTERLY: (3, 6),
    Subscription.Frequency.YEARLY: (12, 8),
}
PAYMENT_PREFIX = re.compile(
    r"^(?:(?:card payment|debit card|pos purchase|pos|payment to)\b\s*[:*\-/ ]*)+", re.I
)
REFERENCE_SUFFIX = re.compile(
    r"(?:\s+(?:ref(?:erence)?|txn|transaction|auth(?:orization)?|order|invoice|"
    r"terminal|card)\s*[:#*\- ]*\d[\w-]*|"
    r"\s+\d{4}[-/.]\d{2}[-/.]\d{2}|(?:\s+[#*]?|[#*]+)\d{4,})$",
    re.I,
)


@dataclass(frozen=True)
class Payment:
    day: date
    amount: Decimal
    merchant: str


def merchant_names(description):
    name = " ".join(unicodedata.normalize("NFKC", description).split())
    name = PAYMENT_PREFIX.sub("", name)
    while (cleaned := REFERENCE_SUFFIX.sub("", name)) != name:
        name = cleaned.rstrip(" *#-")
    name = name.strip(" *#-")
    identity = re.sub(r"^www\.", "", name.casefold())
    identity = re.sub(r"\.(?:com|net|org|bg|co\.uk)$", "", identity)
    normalized = " ".join(re.findall(r"[^\W_]+", identity))
    if not any(char.isalpha() for char in normalized):
        return "", ""
    # Ignore separators and common website suffixes in merchant descriptors.
    return name[:255], normalized.replace(" ", "")[:255]


def shifted_date(day, months, anchor_day):
    year, month = divmod(day.year * 12 + day.month - 1 + months, 12)
    return day.replace(
        year=year, month=month + 1, day=min(anchor_day, monthrange(year, month + 1)[1])
    )


def expected_date(first, frequency, periods, anchor_day):
    months, _ = FREQUENCIES[frequency]
    if months:
        return shifted_date(first, months * periods, anchor_day)
    return first + timedelta(weeks=periods)


def amount_bands(payments):
    bands = []
    for payment in sorted(payments, key=lambda item: item.amount):
        if not bands or payment.amount - bands[-1][0].amount > max(
            Decimal("0.50"), bands[-1][0].amount * Decimal("0.10")
        ):
            bands.append([])
        bands[-1].append(payment)
    return bands


def matching_runs(payments, frequency):
    _, tolerance = FREQUENCIES[frequency]
    run = []
    for payment in sorted(payments, key=lambda item: item.day):
        if run and payment.day == run[-1].day:
            continue
        if run:
            first = run[0].day
            expected = expected_date(first, frequency, len(run), first.day)
            if abs((payment.day - expected).days) > tolerance:
                if len(run) >= 3:
                    yield run
                run = []
        run.append(payment)
    if len(run) >= 3:
        yield run


def estimate(run, frequency):
    days = [payment.day for payment in run]
    month_ends = [monthrange(day.year, day.month)[1] for day in days]
    anchor = (
        31
        if all(day.day == end for day, end in zip(days, month_ends))
        else round(median(day.day for day in days))
    )
    amounts = [payment.amount for payment in run]
    amount = median(amounts)
    _, tolerance = FREQUENCIES[frequency]
    interval_error = sum(
        abs((day - expected_date(days[0], frequency, i, days[0].day)).days)
        for i, day in enumerate(days[1:], 1)
    ) / (len(days) - 1)
    amount_error = float((max(amounts) - min(amounts)) / max(amount, Decimal("5.00")))
    # Compare display spellings as well as the normalized identity used for grouping.
    spelling = run[-1].merchant.casefold()
    similarity = sum(
        SequenceMatcher(None, spelling, payment.merchant.casefold()).ratio()
        for payment in run
    ) / len(run)
    confidence = (
        0.34 * similarity
        + 0.27 * (1 - min(amount_error * 3, 1))
        + 0.29 * (1 - interval_error / (tolerance + 1))
        + 0.10 * min(len(run) / 6, 1)
    )
    return {
        "merchant": run[-1].merchant,
        "estimated_amount": amount.quantize(Decimal("0.01")),
        "next_expected_payment": expected_date(days[0], frequency, len(days), anchor),
        "detection_confidence": Decimal(str(round(confidence, 2))),
    }


def detect_subscriptions(owner):
    groups = defaultdict(list)
    today = timezone.localdate()
    transactions = (
        Transaction.objects.filter(user=owner, amount__lt=0)
        .order_by("timestamp", "pk")
        .values_list("timestamp", "amount", "particulars", "currency")
    )
    for timestamp, amount, description, currency in transactions.iterator():
        day = timezone.localdate(timestamp)
        merchant, normalized = merchant_names(description)
        currency = currency.strip().upper()
        if day <= today and normalized and re.fullmatch(r"[A-Z]{3}", currency):
            groups[normalized, currency].append(Payment(day, -amount, merchant))

    detected = []
    for (normalized, currency), payments in groups.items():
        bands = amount_bands(payments)
        for frequency in FREQUENCIES:
            runs = (run for band in bands for run in matching_runs(band, frequency))
            best = max(runs, key=lambda run: (run[-1].day, len(run)), default=None)
            if best is None:
                continue
            values = estimate(best, frequency)
            if values["detection_confidence"] < Decimal("0.70"):
                continue
            subscription, created = Subscription.objects.get_or_create(
                owner=owner,
                normalized_merchant=normalized,
                currency=currency,
                billing_frequency=frequency,
                defaults=values,
            )
            if not created:
                candidates = Subscription.objects.filter(
                    pk=subscription.pk, status=Subscription.Status.CANDIDATE
                )
                if any(
                    getattr(subscription, key) != value for key, value in values.items()
                ):
                    candidates.update(**values, updated_at=timezone.now())
                    subscription.refresh_from_db()
            detected.append(subscription)
    return sorted(detected, key=lambda item: (item.next_expected_payment, item.pk))
