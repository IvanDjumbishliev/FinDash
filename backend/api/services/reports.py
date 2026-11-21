from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from heapq import heappush, heappushpop

from django.utils import timezone

from api.models import Budget, Transaction
from api.services.budgets import INTERNAL_TRANSFER, ZERO, budget_progress, next_month, spending_delta
from api.services.copilot_tools import DataLimitExceeded, FinancialTools, category_name, money

MAX_REPORT_ROWS = 40_000
LARGEST_EXPENSES = 5


@dataclass
class LedgerTotals:
    income: Decimal = ZERO
    gross_expenses: Decimal = ZERO
    refunds: Decimal = ZERO
    count: int = 0
    categories: dict = field(default_factory=lambda: defaultdict(lambda: ZERO))

    @property
    def expenses(self):
        return self.gross_expenses - self.refunds

    def record(self, amount, description, category):
        if not amount or INTERNAL_TRANSFER.search(description):
            return None
        self.count += 1
        delta = spending_delta(amount, description)
        if delta is None:
            self.income += amount
        elif delta > ZERO:
            self.gross_expenses += delta
            self.categories[category] += delta
        else:
            self.refunds -= delta
            self.categories[category] += delta
        return delta


def period_info(start, end):
    return {
        "month": start.isoformat()[:7], "start_date": start.isoformat(), "end_date": end.isoformat(),
    }


def report_activity(owner, zone, currency, start, end, previous_start, previous_end):
    current, previous = LedgerTotals(), LedgerTotals()
    largest = []
    # Pad the UTC window for timezone offsets and date changes around midnight.
    rows = Transaction.objects.filter(
        user=owner, currency__iexact=currency,
        timestamp__gte=datetime.combine(previous_start - timedelta(days=1), time.min, UTC),
        timestamp__lte=datetime.combine(end + timedelta(days=1), time.max, UTC),
    ).order_by().values_list("pk", "timestamp", "amount", "category", "particulars", "merchant")

    for index, (pk, timestamp, amount, category, description, merchant) in enumerate(
        rows[:MAX_REPORT_ROWS + 1].iterator()
    ):
        if index >= MAX_REPORT_ROWS:
            raise DataLimitExceeded
        day = timestamp.astimezone(zone).date()
        category = category_name(category)
        if previous_start <= day <= previous_end:
            previous.record(amount, description, category)
        elif start <= day <= end:
            delta = current.record(amount, description, category)
            if delta is not None and delta > ZERO:
                label = " ".join((merchant or description).split())[:100] or "Expense"
                expense = (delta, -pk, day, category, label)
                if len(largest) < LARGEST_EXPENSES:
                    heappush(largest, expense)
                else:
                    heappushpop(largest, expense)

    return current, previous, [
        {"date": day.isoformat(), "category": category, "label": label, "amount": money(amount)}
        for amount, _, day, category, label in sorted(largest, reverse=True)
    ]


def generate_report(owner, tools, start, currency, *, generated_at):
    end = min(tools.today, next_month(start) - timedelta(days=1))
    previous_end = start - timedelta(days=1)
    previous_start = previous_end.replace(day=1)
    partial_month = end < next_month(start) - timedelta(days=1)
    if partial_month:
        previous_end = min(previous_end, previous_start + timedelta(days=(end - start).days))

    current, prior, largest = report_activity(
        owner, tools.zone, currency, start, end, previous_start, previous_end,
    )
    can_compare = bool(current.count and prior.count)
    categories = current.categories.keys() | (prior.categories.keys() if can_compare else set())
    comparison = {
        "period": period_info(previous_start, previous_end),
        "has_activity": bool(prior.count),
        "net_expenses": money(prior.expenses) if prior.count else None,
        "change": money(current.expenses - prior.expenses) if can_compare else None,
    }
    budgets = Budget.objects.filter(owner=owner, period=start, currency__iexact=currency, archived=False)
    spending = {(start, budget.currency, budget.category): (
        current.expenses if budget.category is None else current.categories.get(budget.category, ZERO)
    ) for budget in budgets}
    subscriptions = tools.get_subscription_summary(currency=currency)

    return {
        "period": {**period_info(start, end), "partial": partial_month},
        "currency": currency,
        "timezone": tools.zone.key,
        "generated_at": generated_at.astimezone(UTC).isoformat(),
        "activity": {
            "transaction_count": current.count,
            "income": money(current.income),
            "gross_expenses": money(current.gross_expenses),
            "refunds": money(current.refunds),
            "net_expenses": money(current.expenses),
            "net_cash_flow": money(current.income - current.expenses),
        },
        "comparison": comparison,
        "categories": [
            {
                "category": category,
                "net_expenses": money(current.categories[category]),
                "previous_net_expenses": money(prior.categories[category]) if can_compare else None,
                "change": money(current.categories[category] - prior.categories[category]) if can_compare else None,
            }
            for category in sorted(categories, key=lambda name: (-current.categories.get(name, ZERO), name))
        ],
        "largest_expenses": largest,
        "budgets": [
            {"category": category_name(budget.category) if budget.category else None,
             "amount": money(budget.amount), **budget_progress(budget, spending)}
            for budget in budgets
        ],
        "subscriptions": {
            "as_of": tools.today.isoformat(),
            "totals": next(iter(subscriptions["totals"]), None),
            "largest_recurring_expenses": subscriptions["largest_recurring_expenses"],
        },
        "goals": {"available": False, "message": "Financial goal tracking is not available in FinDash."},
    }


def report_tools(owner):
    # Resolve the ledger date and generated timestamp from the same instant.
    now = timezone.now()
    return FinancialTools(owner, now=now), now
