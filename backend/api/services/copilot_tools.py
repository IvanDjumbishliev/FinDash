import re
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db.models import Case, Count, DecimalField, F, Sum, When
from django.utils import timezone

from api.models import Budget, Subscription, Transaction
from api.services.budgets import ZERO, budget_progress, spending_delta
from api.services.subscription_planning import PER_YEAR

MAX_RANGE_DAYS = 366
MAX_RECENT = 20
MAX_CURRENCIES = 12
MAX_SCAN_ROWS = 20_000
DATE_PATTERN = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
CURRENCY_PATTERN = r"[A-Z]{3}"
CATEGORIES = frozenset(Transaction.Category.values)


class InvalidToolCall(ValueError):
    pass


class DataLimitExceeded(Exception):
    pass


def account_timezone(owner):
    profile = getattr(owner, "userprofile", None)
    return ZoneInfo(profile.timezone if profile else "UTC")


def parse_date(value):
    if not isinstance(value, str) or not re.fullmatch(DATE_PATTERN, value):
        raise InvalidToolCall("Use dates in YYYY-MM-DD format.")
    try:
        result = date.fromisoformat(value)
    except ValueError as error:
        raise InvalidToolCall("Enter a valid calendar date.") from error
    if not 2 <= result.year <= 9998:
        raise InvalidToolCall("Enter a date with a representable timezone boundary.")
    return result


def parse_period(args):
    start, end = parse_date(args["start_date"]), parse_date(args["end_date"])
    if not 0 <= (end - start).days < MAX_RANGE_DAYS:
        raise InvalidToolCall("Choose an inclusive range of up to 366 days in date order.")
    return start, end


def parse_limit(limit):
    # Gemini may represent whole JSON numbers as floats.
    if type(limit) not in (int, float) or not 1 <= limit <= MAX_RECENT or limit % 1:
        raise InvalidToolCall("Choose a whole-number limit from 1 to 20.")
    return int(limit)


def currency_code(value):
    code = value.strip().upper()
    return code if re.fullmatch(CURRENCY_PATTERN, code) else None


def category_name(value):
    return value if value in CATEGORIES else "uncategorized"


def money(amount):
    return format(amount, ".2f")


class FinancialTools:
    """Read-only financial projections bound to a server-authenticated account."""

    def __init__(self, owner):
        self.owner = owner
        self.zone = account_timezone(owner)
        self.today = timezone.localdate(timezone=self.zone)

    def _spending(self, start, end):
        # The padded UTC window covers local dates even when a clock rolls back at midnight.
        rows = Transaction.objects.filter(
            user=self.owner,
            timestamp__gte=datetime.combine(start - timedelta(days=1), time.min, UTC),
            timestamp__lte=datetime.combine(end + timedelta(days=1), time.max, UTC),
        ).order_by().values_list("timestamp", "category", "currency", "amount", "particulars")
        totals = defaultdict(lambda: ZERO)
        counts = defaultdict(int)
        for index, (timestamp, category, currency, amount, description) in enumerate(
            rows[:MAX_SCAN_ROWS + 1].iterator()
        ):
            if index == MAX_SCAN_ROWS:
                raise DataLimitExceeded
            if not start <= timestamp.astimezone(self.zone).date() <= end:
                continue
            currency = currency_code(currency)
            if currency is None:
                continue
            delta = spending_delta(amount, description)
            if delta is not None:
                category = category_name(category)
                totals[currency, category] += delta
                counts[currency] += 1

        overall = defaultdict(lambda: ZERO)
        for (currency, _), amount in totals.items():
            overall[currency] += amount
        return overall, totals, counts

    def _observed_result(self, start, end):
        overall, categories, counts = self._spending(start, end)
        currencies = sorted(overall)[:MAX_CURRENCIES]
        summary = {
            "kind": "observed",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "truncated": len(overall) > MAX_CURRENCIES,
            "totals": [
                {"currency": currency, "net_spending": money(overall[currency]),
                 "transaction_count": counts[currency]}
                for currency in currencies
            ],
        }
        return summary, categories

    def get_spending_summary(self, start, end):
        summary, _ = self._observed_result(start, end)
        return summary

    def get_category_breakdown(self, start, end):
        summary, categories = self._observed_result(start, end)
        for entry in summary["totals"]:
            entry["categories"] = {
                category: money(amount)
                for (currency, category), amount in sorted(categories.items())
                if currency == entry["currency"]
            }
        return summary

    def get_recent_transactions(self, limit):
        rows = Transaction.objects.filter(user=self.owner).order_by(
            "-timestamp", "-pk"
        ).values_list("timestamp", "category", "currency", "amount")[:limit]
        return {
            "kind": "observed",
            "transactions": [
                {"date": timestamp.astimezone(self.zone).date().isoformat(),
                 "category": category_name(category),
                 "currency": currency_code(currency), "signed_amount": money(amount)}
                for timestamp, category, currency, amount in rows
                if currency_code(currency)
            ],
        }

    def compare_spending_periods(self, period_a, period_b):
        first, _, _ = self._spending(*period_a)
        second, _, _ = self._spending(*period_b)
        currencies = sorted(first.keys() | second.keys())
        return {
            "kind": "observed",
            "period_a": [day.isoformat() for day in period_a],
            "period_b": [day.isoformat() for day in period_b],
            "truncated": len(currencies) > MAX_CURRENCIES,
            "totals": [
                {"currency": currency, "period_a_net_spending": money(first.get(currency, ZERO)),
                 "period_b_net_spending": money(second.get(currency, ZERO)),
                 "change_b_minus_a": money(second.get(currency, ZERO) - first.get(currency, ZERO))}
                for currency in currencies[:MAX_CURRENCIES]
            ],
        }

    def get_budget_status(self):
        period = self.today.replace(day=1)
        budgets = list(Budget.objects.filter(
            owner=self.owner, period=period, archived=False,
        ).order_by(F("category").asc(nulls_first=True), "pk")[:MAX_CURRENCIES + 1])
        overall, categories, _ = self._spending(period, self.today) if budgets else ({}, {}, {})
        spending = {
            (period, budget.currency, budget.category): (
                overall.get(currency_code(budget.currency), ZERO) if budget.category is None
                else categories.get((currency_code(budget.currency), category_name(budget.category)), ZERO)
            )
            for budget in budgets
        }
        return {
            "kind": "observed", "month": period.isoformat()[:7], "as_of": self.today.isoformat(),
            "truncated": len(budgets) > MAX_CURRENCIES,
            "budgets": [
                {"category": category_name(budget.category) if budget.category else None,
                 "currency": currency_code(budget.currency), "limit": money(budget.amount),
                 **budget_progress(budget, spending)}
                for budget in budgets[:MAX_CURRENCIES]
                if currency_code(budget.currency)
            ],
        }

    def get_subscription_summary(self):
        active = Subscription.objects.filter(
            owner=self.owner, status=Subscription.Status.CONFIRMED,
            currency__regex=rf"^{CURRENCY_PATTERN}$", billing_frequency__in=PER_YEAR,
        ).exclude(tracking_status__in=[
            Subscription.TrackingStatus.PAUSED, Subscription.TrackingStatus.CANCELED,
        ])
        annual_amount = Case(*[
            When(billing_frequency=frequency, then=F("estimated_amount") * count)
            for frequency, count in PER_YEAR.items()
        ], output_field=DecimalField())
        rows = list(active.values("currency").annotate(
            count=Count("pk"), annual=Sum(annual_amount),
        ).order_by("currency")[:MAX_CURRENCIES + 1])
        return {
            "kind": "estimate", "scope": "active_confirmed",
            "truncated": len(rows) > MAX_CURRENCIES,
            "totals": [
                {"currency": row["currency"], "subscription_count": row["count"],
                 "estimated_monthly": money(row["annual"] / Decimal(12)),
                 "estimated_annual": money(row["annual"])}
                for row in rows[:MAX_CURRENCIES]
            ],
        }
