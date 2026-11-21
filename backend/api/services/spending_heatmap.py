from datetime import UTC, datetime, time, timedelta

from api.models import Transaction
from api.services.budgets import ZERO, spending_delta


def daily_spending(owner, start, end, zone, currency):
    """Aggregate the inclusive local date range in a single streamed query."""
    day_count = (end - start).days + 1
    # A clock rollback can bring back the previous date after local midnight.
    # Query a UTC window covering every possible offset, then check local dates.
    lower_bound = datetime.combine(start - timedelta(days=1), time.min, UTC)
    upper_bound = datetime.combine(end + timedelta(days=1), time.max, UTC)

    days = {
        start + timedelta(days=offset): {
            "total_spending": ZERO,
            "transaction_count": 0,
            "category_totals": {},
        }
        for offset in range(day_count)
    }
    transactions = Transaction.objects.filter(
        user=owner,
        timestamp__gte=lower_bound,
        timestamp__lte=upper_bound,
        currency__iexact=currency,
    ).order_by().values_list("timestamp", "category", "amount", "particulars")

    for timestamp, category, amount, particulars in transactions.iterator():
        try:
            day = days.get(timestamp.astimezone(zone).date())
        except OverflowError:
            # The padded window can reach beyond the representable local dates.
            continue
        if day is None:
            continue
        delta = spending_delta(amount, particulars)
        if delta is None:
            continue
        day["total_spending"] += delta
        day["transaction_count"] += 1
        totals = day["category_totals"]
        totals[category] = totals.get(category, ZERO) + delta

    return [
        {
            "date": day.isoformat(),
            "total_spending": format(totals["total_spending"], ".2f"),
            "transaction_count": totals["transaction_count"],
            "category_totals": {
                category: format(amount, ".2f")
                for category, amount in sorted(totals["category_totals"].items())
            },
        }
        for day, totals in days.items()
    ]
