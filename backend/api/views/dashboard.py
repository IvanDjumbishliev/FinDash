from collections import defaultdict
from datetime import datetime, time, timedelta
from heapq import nsmallest

from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework import serializers
from rest_framework.response import Response

from api.models import Budget, CopilotPreferences, FinancialGoal, GroceryOffer, Portfolio, Subscription, Transaction, VirtualTrade
from api.serializers import BudgetSerializer, TransactionSerializer
from api.services.budgets import INTERNAL_TRANSFER, REFUND, ZERO, spending_by_budget
from api.services.copilot_tools import DataLimitExceeded, account_timezone
from api.services.subscription_planning import renewal_dates

from .assistant import PrivateCopilotView
from .deals import cached_deal_highlights

MAX_ACTIVITY_ROWS = 40_000
SECTIONS = ("overview", "monthly", "budgets", "subscriptions", "goals", "portfolio", "deals", "insights")


def activity(owner, start, end):
    totals = defaultdict(lambda: {"income": ZERO, "expenses": ZERO, "refunds": ZERO, "categories": defaultdict(lambda: ZERO)})
    rows = Transaction.objects.filter(
        user=owner, timestamp__gte=start, timestamp__lte=end,
    ).order_by().values_list("currency", "category", "amount", "particulars")
    for index, (currency, category, amount, description) in enumerate(rows[:MAX_ACTIVITY_ROWS + 1].iterator()):
        if index == MAX_ACTIVITY_ROWS:
            raise DataLimitExceeded
        if not amount or INTERNAL_TRANSFER.search(description):
            continue
        row = totals[currency.strip().upper()]
        if amount < 0:
            row["expenses"] -= amount
            row["categories"][category] -= amount
        elif REFUND.search(description):
            row["refunds"] += amount
            row["categories"][category] -= amount
        else:
            row["income"] += amount
    return [
        {
            "currency": currency, "income": str(row["income"]), "expenses": str(row["expenses"] - row["refunds"]),
            "net": str(row["income"] - row["expenses"] + row["refunds"]),
            "categories": {category: str(amount) for category, amount in row["categories"].items()},
        }
        for currency, row in sorted(totals.items())
    ]


def upcoming(owner, today):
    end = today + timedelta(days=31)
    subscriptions = Subscription.objects.filter(
        owner=owner, status=Subscription.Status.CONFIRMED, next_expected_payment__lt=end,
    ).exclude(tracking_status__in=[Subscription.TrackingStatus.PAUSED, Subscription.TrackingStatus.CANCELED])
    def entries():
        for row in subscriptions.iterator():
            for due in renewal_dates(row.next_expected_payment, row.billing_frequency, today, end, row.billing_anchor_day):
                yield {"id": row.pk, "merchant": row.merchant, "date": due.isoformat(),
                       "amount": str(row.estimated_amount), "currency": row.currency}

    return nsmallest(5, entries(), key=lambda row: (row["date"], row["id"]))


class DashboardView(PrivateCopilotView):
    def get(self, request):
        requested = request.query_params.getlist("sections") or [",".join(SECTIONS)]
        sections = set(requested[0].split(",", len(SECTIONS)))
        if len(requested) != 1 or not sections <= set(SECTIONS):
            raise serializers.ValidationError({"sections": "Choose supported dashboard sections."})
        user = request.user
        zone = account_timezone(user)
        now = timezone.now()
        today = timezone.localdate(now, timezone=zone)
        month = today.replace(day=1)
        response = {"month": month.isoformat(), "username": user.username}
        if sections & {"overview", "monthly", "insights"}:
            try:
                response["activity"] = activity(user, datetime.combine(month, time.min, zone), now)
            except DataLimitExceeded:
                response["activity"] = None
        if "insights" in sections:
            preferences = CopilotPreferences.objects.filter(owner=user, history_enabled=True).first()
            answer = preferences.history[-1].get("response", {}).get("answer") if preferences and preferences.history else None
            response["insight"] = (answer[:500] + "…" if len(answer) > 500 else answer) if isinstance(answer, str) else None
        if "overview" in sections:
            recent = Transaction.objects.filter(user=user, timestamp__lte=now).order_by("-timestamp", "-pk")[:5]
            response["recent"] = TransactionSerializer(recent, many=True).data
        if "budgets" in sections:
            # Use the same period and calculation as the Budget Planner.
            budget_period = timezone.localdate(now).replace(day=1)
            response["budget_period"] = budget_period.isoformat()
            budgets = list(Budget.objects.filter(owner=user, period=budget_period, archived=False).order_by("category", "pk")[:5])
            response["budgets"] = BudgetSerializer(
                budgets, many=True, context={"spending": spending_by_budget(user, budgets)},
            ).data
        if "subscriptions" in sections:
            response["subscriptions"] = upcoming(user, today)
        if "goals" in sections:
            response["goals"] = list(FinancialGoal.objects.filter(owner=user, archived=False).order_by()
                                     .values("currency").annotate(count=Count("id"), saved=Sum("current_amount"),
                                                                  target=Sum("target_amount")).order_by("currency"))
            for row in response["goals"]:
                for field in ("saved", "target"):
                    row[field] = format(row[field], ".2f")
        if "portfolio" in sections:
            response["portfolio"] = {
                "count": Portfolio.objects.filter(owner=user).count(),
                "trades": list(VirtualTrade.objects.filter(portfolio__owner=user).order_by("-timestamp", "-pk")
                               .values("id", "ticker", "side", "quantity", "price", "currency")[:3]),
            }
        if "deals" in sections:
            response["deals"] = list(GroceryOffer.objects.current().filter(availability_status="advertised")
                                     .order_by("-last_successful_update", "retailer", "pk")
                                     .values("id", "product_name", "retailer", "price", "currency", "expires_on")[:6])
            for offer in response["deals"]:
                offer["price"] = format(offer["price"], ".2f")
            if not response["deals"]:
                response["deals"] = cached_deal_highlights(now)
        return Response(response)
