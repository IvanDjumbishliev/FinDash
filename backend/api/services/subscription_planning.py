from calendar import monthrange
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from itertools import combinations
from statistics import median

from api.models import Subscription

from .subscriptions import FREQUENCIES, expected_date, matching_runs, merchant_names, payment_groups

WINDOW_DAYS = 90
PER_YEAR = {"weekly": 52, "monthly": 12, "quarterly": 4, "yearly": 1}


def renewal_dates(first, frequency, start, end, anchor_day=None):
    """Yield scheduled dates in the half-open interval [start, end)."""
    months, _ = FREQUENCIES[frequency]
    month_delta = (start.year - first.year) * 12 + start.month - first.month
    elapsed = month_delta // months if months else (start - first).days // 7
    period = max(0, elapsed)
    anchor = anchor_day or (31 if first.day == monthrange(first.year, first.month)[1] else first.day)
    while (due := expected_date(first, frequency, period, anchor)) < end:
        if due >= start:
            yield due
        period += 1


class RenewalSchedule:
    """Evaluate reminder eligibility without storing jobs or sending notifications."""

    def __init__(self, today, preferences):
        self.today = today
        self.preferences = preferences

    def entries(self, records):
        entries = []
        for record in records:
            confirmed = record.status == Subscription.Status.CONFIRMED
            dates = renewal_dates(
                record.next_expected_payment, record.billing_frequency,
                self.today, self.today + timedelta(days=WINDOW_DAYS), record.billing_anchor_day,
            )
            for due in dates:
                lead = self.preferences.reminder_lead_days
                reminder_due = (
                    self.preferences.renewal_reminders and confirmed
                    and (due - self.today).days <= lead
                )
                entries.append({
                    "subscription_id": record.pk, "date": due.isoformat(),
                    "reminder_due": reminder_due,
                })
        return sorted(entries, key=lambda entry: (entry["date"], entry["subscription_id"]))


def was_price_increased(record, payments, today):
    # Compare two consecutive higher charges against three comparable earlier ones.
    runs = matching_runs(payments, record.billing_frequency)
    run = max(runs, key=lambda items: items[-1].day, default=[])
    if len(run) < 5:
        return None
    earlier = [payment.amount for payment in run[-5:-2]]
    recent = [payment.amount for payment in run[-2:]]
    baseline = median(earlier)
    _, tolerance = FREQUENCIES[record.billing_frequency]
    first = run[0].day
    next_charge = expected_date(first, record.billing_frequency, len(run), first.day)
    if next_charge + timedelta(days=tolerance) < today:
        return None
    if max(earlier) - min(earlier) > max(Decimal("0.50"), baseline * Decimal("0.05")):
        return None
    if max(recent) - min(recent) > max(Decimal("0.50"), median(recent) * Decimal("0.05")):
        return None
    if min(recent) - baseline < max(Decimal("0.50"), baseline * Decimal("0.05")):
        return None
    return {"previous_amount": str(baseline), "recent_amount": str(median(recent).quantize(Decimal("0.01")))}


def duplicate_pairs(records, today):
    groups = defaultdict(list)
    for record in records:
        key = (record.normalized_merchant or merchant_names(record.merchant)[1], record.currency)
        if key[0]:
            groups[key].append(record)
    pairs = []
    horizon = today + timedelta(days=366)
    for group in groups.values():
        if len(group) < 2:
            continue
        dates = {
            record.pk: set(renewal_dates(
                record.next_expected_payment, record.billing_frequency, today, horizon,
                record.billing_anchor_day,
            ))
            for record in group
        }
        for left, right in combinations(group, 2):
            for due in sorted(dates[left.pk]):
                if any(due + timedelta(days=offset) in dates[right.pk] for offset in (-2, -1, 0, 1, 2)):
                    pairs.append({"subscription_ids": [left.pk, right.pk], "overlap_date": due.isoformat()})
                    break
    return pairs


def monthly_summary(records, renewals, today):
    totals = defaultdict(lambda: {"remaining": Decimal(0), "annual": Decimal(0)})
    active = {record.pk: record for record in records if record.status == Subscription.Status.CONFIRMED}
    for record in active.values():
        totals[record.currency]["annual"] += record.estimated_amount * PER_YEAR[record.billing_frequency]
    month = today.isoformat()[:7]
    count = 0
    for renewal in renewals:
        record = active.get(renewal["subscription_id"])
        if record and renewal["date"].startswith(month):
            totals[record.currency]["remaining"] += record.estimated_amount
            count += 1
    return {
        "month": month, "renewal_count": count,
        "totals": [
            {"currency": currency, "remaining": str(values["remaining"].quantize(Decimal("0.01"))),
             "monthly": str((values["annual"] / 12).quantize(Decimal("0.01"))),
             "annual": str(values["annual"].quantize(Decimal("0.01")))}
            for currency, values in sorted(totals.items())
        ],
    }


def subscription_plan(owner, records, preferences, today):
    renewals = RenewalSchedule(today, preferences).entries(records)
    keys = {(record.normalized_merchant, record.currency) for record in records}
    groups = payment_groups(owner, today, keys, since=today - timedelta(days=1850)) if keys else {}
    increases = []
    for record in records:
        payments = groups.get((record.normalized_merchant, record.currency), [])
        if change := was_price_increased(record, payments, today):
            increases.append({"subscription_id": record.pk, **change})
    return {
        "as_of": today.isoformat(),
        "renewals": renewals,
        "duplicates": duplicate_pairs(records, today),
        "price_increases": increases,
        "summary": monthly_summary(records, renewals, today) if preferences.monthly_summary else None,
    }
