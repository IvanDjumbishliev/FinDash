from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median

from django.db import transaction
from django.db.models.functions import Upper
from django.utils import timezone

from api.models import Budget, NotificationCategory as Category, NotificationStockAlert, Stock, Subscription, SubscriptionPreferences, Transaction
from api.services.budgets import INTERNAL_TRANSFER, budget_progress, spending_by_budget
from api.services.copilot_tools import account_timezone
from api.services.notifications import categories_for, notify
from api.services.portfolio_quotes import market_quote
from api.services.subscription_planning import RenewalSchedule

MAX_QUOTE_AGE = timedelta(hours=36)


def check_budgets(owner_id, periods):
    if not periods or not categories_for(owner_id)[Category.BUDGET_THRESHOLD]:
        return 0
    budgets = list(Budget.objects.filter(owner_id=owner_id, period__in=periods, archived=False))
    spending = spending_by_budget(owner_id, budgets)
    count = 0
    for budget in budgets:
        for threshold in budget_progress(budget, spending)["reached_thresholds"]:
            count += bool(notify(owner_id, Category.BUDGET_THRESHOLD, f"{budget.pk}:{budget.period}:{threshold}"))
    return count


def check_unusual_spending(owner_id, rows, now):
    if not categories_for(owner_id)[Category.UNUSUAL_SPENDING]:
        return
    recent = now - timedelta(days=7)
    candidates = [row for row in rows if recent <= row.timestamp <= now and row.amount < 0
                  and not INTERNAL_TRANSFER.search(row.particulars)]
    if not candidates:
        return
    references = defaultdict(list)
    dates = defaultdict(set)
    history = Transaction.objects.annotate(code=Upper("currency")).filter(
        user_id=owner_id, amount__lt=0, timestamp__gte=recent - timedelta(days=90), timestamp__lt=recent,
        code__in={row.currency.upper() for row in candidates}, category__in={row.category for row in candidates},
    ).order_by().values_list("code", "category", "amount", "timestamp", "particulars")
    for index, (currency, category, amount, timestamp, particulars) in enumerate(history[:20_001].iterator()):
        if index == 20_000:
            return
        if not INTERNAL_TRANSFER.search(particulars):
            key = currency, category
            references[key].append(-amount)
            dates[key].add(timestamp.date())
    thresholds = {}
    for key, values in references.items():
        if len(values) >= 8 and len(dates[key]) >= 4:
            middle = median(values)
            deviation = median(abs(value - middle) for value in values)
            thresholds[key] = max(3 * middle, middle + 6 * deviation)
    for row in candidates:
        threshold = thresholds.get((row.currency.upper(), row.category))
        if threshold is not None and -row.amount >= threshold:
            notify(owner_id, Category.UNUSUAL_SPENDING, row.pk)


def check_spending_rows(owner_id, *, transaction_id=None, import_id=None):
    rows = Transaction.objects.filter(user_id=owner_id)
    if transaction_id is not None:
        rows = rows.filter(pk=transaction_id)
    elif import_id is not None:
        rows = rows.filter(statement_import_id=import_id)
    else:
        return
    rows = list(rows.only("timestamp", "amount", "particulars", "currency", "category"))
    check_budgets(owner_id, {timezone.localtime(row.timestamp).date().replace(day=1) for row in rows})
    check_unusual_spending(owner_id, rows, timezone.now())


def transaction_recorded(owner_id, transaction_id):
    check_spending_rows(owner_id, transaction_id=transaction_id)


def statement_imported(owner_id, import_id):
    notify(owner_id, Category.STATEMENT_IMPORT, import_id)
    check_spending_rows(owner_id, import_id=import_id)


def report_generated(owner_id, month, currency, day):
    notify(owner_id, Category.FINANCIAL_REPORT, f"{month}:{currency}:{day.isoformat()}")


def generate_renewal_alerts(owner, *, now=None):
    if not categories_for(owner.pk)[Category.SUBSCRIPTION_RENEWAL]:
        return 0
    preferences = SubscriptionPreferences.objects.filter(owner=owner, renewal_reminders=True).first()
    if not preferences:
        return 0
    today = timezone.localdate(now, timezone=account_timezone(owner))
    records = Subscription.objects.filter(owner=owner, status=Subscription.Status.CONFIRMED).exclude(
        tracking_status__in=[Subscription.TrackingStatus.PAUSED, Subscription.TrackingStatus.CANCELED],
    )
    return sum(bool(notify(owner.pk, Category.SUBSCRIPTION_RENEWAL, f"{entry['subscription_id']}:{entry['date']}"))
               for entry in RenewalSchedule(today, preferences).entries(records) if entry["reminder_due"])


def generate_stock_alerts(owner, *, now=None):
    if not categories_for(owner.pk)[Category.STOCK_THRESHOLD]:
        return 0
    now = now or timezone.now()
    watchlist = Stock.objects.filter(user=owner).values_list("ticker", flat=True)
    rules = NotificationStockAlert.objects.filter(owner=owner, ticker__in=watchlist)
    count = 0
    for rule in rules:
        quote = market_quote(rule.ticker)
        observed = quote.get("timestamp")
        price = quote.get("price")
        if (quote.get("status") != "quoted" or quote.get("currency") != rule.currency
                or not isinstance(observed, datetime) or timezone.is_naive(observed)
                or not isinstance(price, Decimal) or not price.is_finite() or price <= 0
                or not now - MAX_QUOTE_AGE <= observed <= now):
            continue
        with transaction.atomic():
            latest = NotificationStockAlert.objects.select_for_update().filter(pk=rule.pk, owner=owner).first()
            if not latest or latest.last_quote_at is not None and observed <= latest.last_quote_at:
                continue
            met = price >= latest.target if latest.direction == NotificationStockAlert.Direction.ABOVE else price <= latest.target
            claimed = NotificationStockAlert.objects.filter(pk=latest.pk, last_quote_at=latest.last_quote_at).update(
                last_quote_at=observed, was_met=met,
            )
            if claimed and met and not latest.was_met:
                count += bool(notify(owner.pk, Category.STOCK_THRESHOLD, f"{latest.pk}:{observed.isoformat()}"))
    return count
