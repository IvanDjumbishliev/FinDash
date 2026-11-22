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
from api.services.copilot_tools import account_timezone
from api.services.subscription_planning import renewal_dates

from .assistant import PrivateCopilotView
from .deals import cached_deal_highlights

SECTIONS = ("overview", "monthly", "budgets", "subscriptions", "goals", "portfolio", "deals", "insights")


def activity(owner, start, end):
    totals = defaultdict(lambda: {"income": ZERO, "expenses": ZERO, "refunds": ZERO, "categories": defaultdict(lambda: ZERO)})
    rows = Transaction.objects.filter(
        user=owner, timestamp__gte=start, timestamp__lt=end,
    ).order_by().values_list("currency", "category", "amount", "particulars")
    for currency, category, amount, description in rows.iterator():
        if not amount or INTERNAL_TRANSFER.search(description):
            continue
        row = totals[currency.upper()]
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
            due = next(renewal_dates(row.next_expected_payment, row.billing_frequency, today, end, row.billing_anchor_day), None)
            if due:
                yield {"id": row.pk, "merchant": row.merchant, "date": due.isoformat(),
                       "amount": str(row.estimated_amount), "currency": row.currency}

    return nsmallest(5, entries(), key=lambda row: (row["date"], row["id"]))


class DashboardView(PrivateCopilotView):
    def get(self, request):
        requested = request.query_params.get("sections", ",".join(SECTIONS))
        sections = set(requested.split(","))
        if not sections <= set(SECTIONS):
            raise serializers.ValidationError({"sections": "Choose supported dashboard sections."})
        user = request.user
        zone = account_timezone(user)
        today = timezone.localdate(timezone=zone)
        month = today.replace(day=1)
        response = {"month": month.isoformat(), "username": user.username}
        if sections & {"overview", "monthly", "insights"}:
            response["activity"] = activity(
                user, datetime.combine(month, time.min, zone), datetime.combine(today + timedelta(days=1), time.min, zone),
            )
        if "insights" in sections:
            preferences = CopilotPreferences.objects.filter(owner=user, history_enabled=True).first()
            answer = preferences.history[-1].get("response", {}).get("answer") if preferences and preferences.history else None
            response["insight"] = answer[:500] if isinstance(answer, str) else None
        if "overview" in sections:
            recent = Transaction.objects.filter(user=user).order_by("-timestamp", "-pk")[:5]
            response["recent"] = TransactionSerializer(recent, many=True).data
        if "budgets" in sections:
            # Use the same period and calculation as the Budget Planner.
            budgets = list(Budget.objects.filter(owner=user, period=timezone.localdate().replace(day=1), archived=False))
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
                response["deals"] = cached_deal_highlights()
        return Response(response)
