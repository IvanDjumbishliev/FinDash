from datetime import UTC, datetime, time, timedelta

from api.models import Transaction
from api.services.budgets import ZERO, spending_delta


def spending_rows(owner, start, end, zone, currency, *, details=False):
    # A clock rollback can bring back the previous date after local midnight.
    # Query a UTC window covering every possible offset, then check local dates.
    lower_bound = datetime.combine(start - timedelta(days=1), time.min, UTC)
    upper_bound = datetime.combine(end + timedelta(days=1), time.max, UTC)
    transactions = Transaction.objects.filter(
        user=owner,
        timestamp__gte=lower_bound,
        timestamp__lte=upper_bound,
        currency__iexact=currency,
    )
    fields = ["timestamp", "category", "amount", "particulars"]
    if details:
        fields.extend(["id", "merchant"])
        transactions = transactions.order_by("-timestamp", "-id")

    for row in transactions.values(*fields).iterator():
        try:
            day = row["timestamp"].astimezone(zone).date()
        except OverflowError:
            continue
        if start <= day <= end:
            delta = spending_delta(row["amount"], row["particulars"])
            if delta is not None:
                yield day, delta, row


def daily_spending(owner, start, end, zone, currency):
    """Aggregate the inclusive local date range in a single streamed query."""
    days = {
        start + timedelta(days=offset): {
            "total_spending": ZERO,
            "transaction_count": 0,
            "category_totals": {},
            "category_counts": {},
        }
        for offset in range((end - start).days + 1)
    }
    for date, delta, row in spending_rows(owner, start, end, zone, currency):
        day = days[date]
        category = row["category"]
        day["total_spending"] += delta
        day["transaction_count"] += 1
        totals = day["category_totals"]
        totals[category] = totals.get(category, ZERO) + delta
        counts = day["category_counts"]
        counts[category] = counts.get(category, 0) + 1

    return [
        {
            "date": day.isoformat(),
            "total_spending": format(totals["total_spending"], ".2f"),
            "transaction_count": totals["transaction_count"],
            "category_totals": {
                category: format(amount, ".2f")
                for category, amount in sorted(totals["category_totals"].items())
            },
            "category_counts": totals["category_counts"],
        }
        for day, totals in days.items()
    ]
