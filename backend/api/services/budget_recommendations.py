import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from statistics import mean, pstdev

from api.models import Budget, Transaction

from .budgets import CENT, ZERO, monthly_spending, next_month

MIN_MONTHS = 3
MAX_MONTHS = 6
MAX_BUDGET = Decimal("99999999.99")


def previous_months(period):
    months = []
    for _ in range(MAX_MONTHS):
        if period == date.min:
            break
        year, month = divmod(period.year * 12 + period.month - 2, 12)
        period = date(year, month + 1, 1)
        months.append(period)
    return list(reversed(months))


def money(value):
    return str(value.quantize(CENT, rounding=ROUND_HALF_UP))


def category_recommendation(months, amounts):
    average = mean(amounts)
    deviation = pstdev(amounts)
    recent = amounts[-3:]
    rising = (
        recent[0] > ZERO
        and recent[0] < recent[1] < recent[2]
        and recent[2] >= recent[0] * Decimal("1.10")
        and all(next_month(left) == right for left, right in zip(months[-3:], months[-2:]))
    )
    # Use the recent average on a sustained rise, plus a bounded variability buffer.
    baseline = max(average, mean(recent)) if rising else average
    buffer = min(deviation / 2, baseline * Decimal("0.15"))
    suggested = money(baseline + buffer)
    if not ZERO < Decimal(suggested) <= MAX_BUDGET:
        return None
    explanation = (
        "The last three observed months were consecutive and spending rose each month by a total of at least 10%. "
        "The starting point is the higher of the recent three-month average and the full observed average."
        if rising else "The starting point is the average across observed months."
    )
    explanation += (
        " The suggestion adds half the monthly standard deviation, capped at 15% of the starting point."
        " Observed months with no spending in this category count as zero."
    )
    return {
        "suggested_amount": suggested,
        "explanation": explanation,
        "statistics": {
            "months_analyzed": len(months),
            "average": money(average),
            "standard_deviation": money(deviation),
            "baseline": money(baseline),
            "variability_buffer": money(buffer),
            "trend": "increasing" if rising else "no_sustained_increase",
            "monthly_spending": [
                {"period": month.isoformat(), "amount": money(amount)}
                for month, amount in zip(months, amounts)
            ],
        },
    }


def generate_recommendations(owner, period, current_month):
    end = min(period, current_month)
    months = previous_months(end)
    if len(months) < MIN_MONTHS:
        return [], {}

    spending, observed = monthly_spending(owner, months[0], end)
    covered = {
        currency: [month for month in months if month in observed_months]
        for currency, observed_months in observed.items()
        if re.fullmatch(r"[A-Z]{3}", currency) and len(observed_months) >= MIN_MONTHS
    }
    existing = {
        budget.category: budget for budget in Budget.objects.filter(
            owner=owner, period=period, archived=False, category__isnull=False,
        )
    }
    suggestions = []
    for category in Transaction.Category.values:
        budget = existing.get(category)
        currencies = [budget.currency] if budget and budget.currency in covered else covered if not budget else []
        options = []
        for currency in currencies:
            eligible = covered[currency]
            amounts = [max(ZERO, spending.get((month, currency, category), ZERO)) for month in eligible]
            positive_months = sum(amount > ZERO for amount in amounts)
            if positive_months < MIN_MONTHS:
                continue
            if recommendation := category_recommendation(eligible, amounts):
                options.append((positive_months, len(eligible), currency, recommendation))
        if options:
            # Compare coverage counts instead of comparing monetary amounts across currencies.
            _, _, currency, recommendation = min(options, key=lambda item: (-item[0], -item[1], item[2]))
            suggestions.append({
                "category": category, "currency": currency,
                "current_amount": money(budget.amount) if budget else None,
                **recommendation,
            })

    return suggestions, existing
