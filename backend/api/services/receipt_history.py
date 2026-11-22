"""Receipt reporting and candidate matching from the owner's ledger."""
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, Exists, F, OuterRef, Q, Sum
from django.db.models.functions import Trim, Upper

from api.models import Receipt, ReceiptItem, Transaction
from api.services.budgets import INTERNAL_TRANSFER
from api.services.grocery_catalog import normalized
from api.services.receipts import SOFIA, product_identity
from api.services.statements.intelligence import merchant_identity

MATCH_WINDOW_DAYS = 3
BREAKDOWN_LIMIT = 25


def local_boundary(day):
    return datetime.combine(day, time.min, tzinfo=SOFIA)


def filter_receipts(receipts, filters):
    if start := filters.get("start"):
        receipts = receipts.filter(purchased_at__gte=local_boundary(start))
    if end := filters.get("end"):
        receipts = receipts.filter(purchased_at__lt=local_boundary(end + timedelta(days=1)))
    if store := filters.get("store"):
        receipts = receipts.filter(Q(merchant__icontains=store) | Q(normalized_merchant__contains=normalized(store)))
    if product := filters.get("product"):
        items = ReceiptItem.objects.filter(receipt_id=OuterRef("pk")).filter(
            Q(original_description__icontains=product) | Q(normalized_name__contains=product_identity(product)),
        )
        receipts = receipts.filter(Exists(items))
    return receipts


def amount_string(amount):
    return format(amount if amount is not None else Decimal("0"), ".2f")


def receipt_statistics(receipts):
    items = ReceiptItem.objects.filter(receipt__in=receipts.order_by()).order_by()
    totals = list(receipts.order_by().alias(payment_currency=Upper(Trim("transaction__currency"))).values("currency").annotate(
        receipt_total=Sum("total"), receipt_count=Count("id"),
        linked_count=Count("transaction", filter=Q(
            transaction__user=F("owner"), payment_currency=F("currency"),
            transaction__amount=-F("total"),
        )),
    ).order_by("currency"))

    def breakdown(currency, group_field):
        rows = (items.filter(receipt__currency=currency).values(group_field)
                .annotate(total=Sum("line_total"), line_count=Count("id"))
                .order_by("-total", group_field)[:BREAKDOWN_LIMIT + 1])
        values = [{"name": row[group_field], "total": amount_string(row["total"]), "line_count": row["line_count"]}
                  for row in rows]
        return values[:BREAKDOWN_LIMIT], len(values) > BREAKDOWN_LIMIT

    item_totals = {
        row["receipt__currency"]: row["total"]
        for row in items.values("receipt__currency").annotate(total=Sum("line_total"))
    }
    for row in totals:
        currency = row["currency"]
        row["total"] = amount_string(row.pop("receipt_total"))
        row["item_total"] = amount_string(item_totals.get(currency))
        row["categories"], row["categories_truncated"] = breakdown(currency, "category")
        row["products"], row["products_truncated"] = breakdown(currency, "normalized_name")
    return totals


def matching_transactions(receipt):
    """Rank compatible payments. Dates and merchant names are evidence, not consent."""
    day = receipt.purchased_at.astimezone(SOFIA).date()
    if not 1900 <= day.year < 9999 or not receipt.total:
        return []
    since = local_boundary(day - timedelta(days=MATCH_WINDOW_DAYS))
    until = local_boundary(day + timedelta(days=MATCH_WINDOW_DAYS + 1))
    linked_elsewhere = Receipt.objects.filter(transaction_id=OuterRef("pk")).exclude(pk=receipt.pk)
    candidates = (Transaction.objects.alias(payment_currency=Upper(Trim("currency"))).filter(
        user_id=receipt.owner_id, amount=-receipt.total, payment_currency=receipt.currency,
        timestamp__gte=since, timestamp__lt=until,
    ).exclude(Exists(linked_elsewhere)).order_by("-timestamp", "-pk")[:200])
    ranked = []
    identity = receipt.normalized_merchant
    for payment in candidates:
        if INTERNAL_TRANSFER.search(payment.particulars):
            continue
        label, merchant = merchant_identity(payment.merchant or payment.particulars)
        merchant = payment.normalized_merchant or merchant
        if identity and merchant == identity:
            match = "exact"
        elif len(identity) >= 4 and len(merchant) >= 4 and (
            f" {identity} " in f" {merchant} " or f" {merchant} " in f" {identity} "
        ):
            match = "partial"
        else:
            match = "unknown"
        distance = abs((payment.timestamp.astimezone(SOFIA).date() - day).days)
        ranked.append({
            "id": payment.pk, "merchant": label[:255], "timestamp": payment.timestamp,
            "amount": amount_string(payment.amount), "currency": receipt.currency,
            "days_apart": distance, "merchant_match": match,
            "confidence": "high" if match == "exact" and distance == 0 else "review",
        })
    ranked.sort(key=lambda entry: (
        {"exact": 0, "partial": 1, "unknown": 2}[entry["merchant_match"]], entry["days_apart"], -entry["id"],
    ))
    if sum(entry["confidence"] == "high" for entry in ranked) > 1:
        for entry in ranked:
            entry["confidence"] = "review"
    return ranked[:10]
