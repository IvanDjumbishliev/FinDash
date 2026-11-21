import re
from collections import defaultdict
from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone

from api.models import Transaction

ZERO = Decimal("0.00")
CENT = Decimal("0.01")
REFUND = re.compile(
    r"\b(?:refund(?:ed)?|merchant reversal|purchase reversal|card reversal|chargeback|"
    r"възстановен[аио]? сум[аи]|възстановяване на сум[аи]|сторно)\b",
    re.IGNORECASE,
)
INTERNAL_TRANSFER = re.compile(
    r"\b(?:internal transfer|self[- ]transfer|own accounts? transfer|"
    r"transfer between (?:(?:my|own|personal) )?accounts|"
    r"transfer (?:to|from) (?:my |own |personal )(?:accounts?|savings)|"
    r"transfer (?:to|from) savings|"
    r"вътрешен превод|превод между (?:мои |собствени )?сметки)\b",
    re.IGNORECASE,
)


def parse_month(value):
    """Accept YYYY-MM or the first day of that month in ISO format."""
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}(?:-01)?", value):
        raise ValueError("Use YYYY-MM or YYYY-MM-01 for a calendar month.")
    try:
        period = date.fromisoformat(f"{value}-01" if len(value) == 7 else value)
    except ValueError as error:
        raise ValueError("Enter a valid calendar month.") from error
    if period.year == 9999 and period.month == 12:
        raise ValueError("The month must have a representable end date.")
    return period


def next_month(period):
    if period.month == 12:
        return date(period.year + 1, 1, 1)
    return date(period.year, period.month + 1, 1)


def month_boundary(period):
    return timezone.make_aware(datetime.combine(period, time.min))


def spending_by_budget(owner, budgets):
    if not budgets:
        return {}

    keys = {(budget.period, budget.currency) for budget in budgets}
    first = min(budget.period for budget in budgets)
    last = max(budget.period for budget in budgets)
    transactions = Transaction.objects.filter(
        user=owner, timestamp__gte=month_boundary(first),
        timestamp__lt=month_boundary(next_month(last)),
    ).values_list("timestamp", "currency", "category", "amount", "particulars")

    spending = defaultdict(lambda: ZERO)
    for timestamp, currency, category, amount, particulars in transactions.iterator():
        month = timezone.localtime(timestamp).date().replace(day=1)
        currency = currency.strip().upper()
        if (month, currency) not in keys or INTERNAL_TRANSFER.search(particulars):
            continue
        if amount < 0 or (amount > 0 and REFUND.search(particulars)):
            spending[month, currency, category] -= amount
            spending[month, currency, None] -= amount
    return spending


def budget_progress(budget, spending):
    spent = max(ZERO, spending.get((budget.period, budget.currency, budget.category), ZERO))
    percent = spent * 100 / budget.amount
    return {
        "actual_spending": str(spent.quantize(CENT)),
        "remaining": str((budget.amount - spent).quantize(CENT)),
        "percentage_used": str(percent.quantize(CENT, rounding=ROUND_HALF_UP)),
        "reached_thresholds": [
            threshold for threshold in budget.alert_thresholds
            if spent * 100 >= budget.amount * threshold
        ],
    }
