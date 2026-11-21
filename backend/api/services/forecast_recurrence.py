from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from statistics import median

from api.models import Subscription
from api.services.subscriptions import FREQUENCIES, amount_bands, merchant_names, shifted_date

CADENCES = {
    frequency: (months, 0 if months else 7, tolerance, 3 if months else 4)
    for frequency, (months, tolerance) in FREQUENCIES.items()
}
CADENCES["biweekly"] = (0, 14, 2, 3)


@dataclass(frozen=True)
class LedgerEntry:
    id: int
    day: date
    amount: Decimal
    kind: str
    merchant: str
    identity: str


@dataclass(frozen=True)
class Schedule:
    label: str
    identity: str
    kind: str
    amount: Decimal
    frequency: str
    anchor: int
    first: date
    source: str
    observations: int | None = None

    def due_at(self, periods):
        months, days, _, _ = CADENCES[self.frequency]
        if months:
            return shifted_date(self.first, months * periods, self.anchor)
        return self.first + timedelta(days=days * periods)

    def period_near(self, day):
        months, days, _, _ = CADENCES[self.frequency]
        if months:
            return ((day.year - self.first.year) * 12 + day.month - self.first.month) // months
        return (day - self.first).days // days

    def dates(self, start, end):
        # Never project a detected amount before its next estimated date.
        initial = max(0, self.period_near(start))
        for offset in range(initial, self.period_near(end) + 2):
            due = self.due_at(offset)
            if due > end:
                break
            if due >= start:
                yield due

    def closest(self, day):
        offset = self.period_near(day)
        return min((self.due_at(index) for index in (offset - 1, offset, offset + 1)),
                   key=lambda due: abs((day - due).days))


def end_of_month(day):
    return day.day == monthrange(day.year, day.month)[1]


def subscription_schedule(subscription):
    label, fallback = merchant_names(subscription.merchant)
    _, identity = merchant_names(subscription.normalized_merchant)
    first = subscription.next_expected_payment
    return Schedule(
        label=label or "Subscription",
        identity=identity or fallback,
        kind="expense",
        amount=subscription.estimated_amount,
        frequency=subscription.billing_frequency,
        anchor=subscription.billing_anchor_day or (31 if end_of_month(first) else first.day),
        first=first,
        source="confirmed_subscription",
    )


def matching_subscription_entries(schedule, entries):
    """Assign at most one amount-compatible charge to each expected payment date."""
    _, _, tolerance, _ = CADENCES[schedule.frequency]
    amount_tolerance = max(Decimal("0.50"), schedule.amount * Decimal("0.20"))
    matches = {}
    for entry in entries:
        amount_error = abs(entry.amount - schedule.amount)
        if amount_error > amount_tolerance:
            continue
        due = schedule.closest(entry.day)
        date_error = abs((entry.day - due).days)
        rank = (date_error, amount_error, entry.id)
        if date_error <= tolerance and (due not in matches or rank < matches[due][0]):
            matches[due] = (rank, entry.id)
    return {entry_id for _, entry_id in matches.values()}


def consecutive_runs(entries, frequency):
    months, days, tolerance, minimum = CADENCES[frequency]
    run = []
    for entry in entries:
        if run:
            if entry.day == run[-1].day:
                continue
            first = run[0].day
            expected = (shifted_date(first, months * len(run), first.day) if months
                        else first + timedelta(days=days * len(run)))
            if abs((entry.day - expected).days) > tolerance:
                if len(run) >= minimum:
                    yield run
                run = []
        run.append(entry)
    if len(run) >= minimum:
        yield run


def inferred_schedule(run, frequency):
    first = run[0].day
    anchor = 31 if all(end_of_month(item.day) for item in run) else round(median(item.day.day for item in run))
    months, days, _, _ = CADENCES[frequency]
    if months:
        due = shifted_date(first, months * len(run), anchor)
    else:
        due = first + timedelta(days=days * len(run))
    return Schedule(
        label=run[-1].merchant, identity=run[-1].identity, kind=run[-1].kind,
        amount=median(item.amount for item in run).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        frequency=frequency,
        anchor=anchor, first=due, source="detected_history", observations=len(run),
    )


def detect_band(band, as_of, known, used):
    entries = sorted((entry for entry in band if entry.id not in used), key=lambda item: (item.day, item.id))
    choices = []
    for frequency, (_, _, tolerance, _) in CADENCES.items():
        for run in consecutive_runs(entries, frequency):
            schedule = inferred_schedule(run, frequency)
            if any(
                pattern.frequency == frequency
                and abs((pattern.closest(schedule.first) - schedule.first).days) <= tolerance
                for pattern in known
            ):
                # A tracked subscription already accounts for this cadence, even if its price changed.
                used.update(entry.id for entry in run)
            elif schedule.first >= as_of - timedelta(days=tolerance):
                choices.append((schedule, run))
    eligible = [(schedule, run) for schedule, run in choices if not any(item.id in used for item in run)]
    if not eligible:
        return None
    schedule, run = max(eligible, key=lambda item: (item[1][-1].day, len(item[1])))
    used.update(entry.id for entry in run)
    used.update(matching_subscription_entries(schedule, entries))
    return schedule


def recurring_schedules(entries, subscriptions, as_of):
    groups = defaultdict(list)
    for entry in entries:
        if entry.kind != "refund" and entry.identity:
            groups[entry.kind, entry.identity].append(entry)

    known = defaultdict(list)
    scheduled = []
    used = set()
    for record in subscriptions:
        if record.billing_frequency not in FREQUENCIES or record.estimated_amount <= 0:
            continue
        schedule = subscription_schedule(record)
        key = (schedule.kind, schedule.identity)
        inactive = record.tracking_status in (Subscription.TrackingStatus.CANCELED, Subscription.TrackingStatus.PAUSED)
        if record.status != Subscription.Status.CONFIRMED and not inactive:
            continue
        known[key].append(schedule)
        if schedule.identity:
            used.update(matching_subscription_entries(schedule, (item for item in groups[key] if item.id not in used)))
        if not inactive:
            scheduled.append(schedule)

    for key, payments in groups.items():
        # Look for recurring charges beyond the known subscription ledger matches.
        patterns = known.get(key, ())
        for band in amount_bands(payments):
            if schedule := detect_band(band, as_of, patterns, used):
                scheduled.append(schedule)

    return scheduled, used
