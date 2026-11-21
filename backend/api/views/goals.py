from decimal import Decimal

from django.db import connection, transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response

from api.models import FinancialGoal, GoalContribution
from api.services.copilot_tools import account_timezone
from api.services.goals import GoalLedgerError, ZERO, project_goal, record_entry, remaining_amount

from .assistant import PrivateCopilotView, StrictBooleanField
from .portfolios import CurrencyField


def money(**kwargs):
    return serializers.DecimalField(max_digits=14, decimal_places=2, **kwargs)


class GoalSerializer(serializers.ModelSerializer):
    currency = CurrencyField(required=True)
    target_amount = money(min_value=Decimal("0.01"))
    monthly_contribution = money(min_value=ZERO, allow_null=True, required=False)
    archived = StrictBooleanField(required=False)
    remaining_amount = serializers.SerializerMethodField()
    progress_percent = serializers.SerializerMethodField()
    completed = serializers.SerializerMethodField()

    class Meta:
        model = FinancialGoal
        fields = (
            "id", "name", "target_amount", "currency", "target_date", "monthly_contribution",
            "current_amount", "remaining_amount", "progress_percent", "completed", "archived",
            "created_at", "updated_at",
        )
        read_only_fields = ("current_amount", "created_at", "updated_at")

    def validate_currency(self, currency):
        if self.instance and currency != self.instance.currency:
            raise serializers.ValidationError("A goal’s currency cannot be changed after creation.")
        return currency

    def get_remaining_amount(self, goal):
        return format(remaining_amount(goal), ".2f")

    def get_progress_percent(self, goal):
        return format(goal.current_amount * 100 / goal.target_amount, ".2f")

    def get_completed(self, goal):
        return goal.current_amount >= goal.target_amount


class ContributionInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=GoalContribution.Kind.choices)
    amount = money(min_value=Decimal("0.01"))
    currency = CurrencyField(required=False)
    note = serializers.CharField(max_length=255, allow_blank=True, required=False)
    request_id = serializers.UUIDField(required=False)

    def validate_currency(self, currency):
        if currency != self.context["goal"].currency:
            raise serializers.ValidationError("Use the goal’s currency for this entry.")
        return currency


class ContributionOutput(serializers.ModelSerializer):
    currency = serializers.CharField(source="goal.currency")

    class Meta:
        model = GoalContribution
        fields = ("id", "kind", "amount", "currency", "balance_after", "note", "request_id", "created_at")


class ProjectionQuery(serializers.Serializer):
    monthly_contribution = money(min_value=ZERO, required=False)


class ProjectionOutput(serializers.Serializer):
    as_of = serializers.DateField()
    currency = serializers.CharField()
    target_date = serializers.DateField(allow_null=True)
    remaining_amount = money()
    monthly_contribution = money(allow_null=True)
    months_remaining = serializers.IntegerField(allow_null=True)
    projected_completion_date = serializers.DateField(allow_null=True)
    projected_on_time = serializers.BooleanField(allow_null=True)
    status = serializers.CharField()


class ContributionPagination(LimitOffsetPagination):
    default_limit = 25
    max_limit = 100


class GoalView(PrivateCopilotView):
    def owned(self):
        return FinancialGoal.objects.filter(owner=self.request.user)

    def get_goal(self, pk, *, lock=False):
        goals = self.owned().filter(pk=pk)
        if lock:
            if connection.vendor == "sqlite":
                # SQLite has no row locks. Take its write lock before reading the balance.
                goals.update(updated_at=F("updated_at"))
            goals = goals.select_for_update()
        return get_object_or_404(goals)


class GoalListView(GoalView):
    def get(self, request):
        return Response(GoalSerializer(self.owned(), many=True).data)

    def post(self, request):
        serializer = GoalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(owner=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class GoalDetailView(GoalView):
    def get(self, request, pk):
        return Response(GoalSerializer(self.get_goal(pk)).data)

    @transaction.atomic
    def patch(self, request, pk):
        serializer = GoalSerializer(self.get_goal(pk, lock=True), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @transaction.atomic
    def delete(self, request, pk):
        goal = self.get_goal(pk, lock=True)
        if goal.contributions.exists():
            return Response({"detail": "Archive goals with contribution history to preserve their ledger."},
                            status=status.HTTP_409_CONFLICT)
        goal.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class GoalContributionView(GoalView):
    def get(self, request, pk):
        goal = self.get_goal(pk)
        pager = ContributionPagination()
        page = pager.paginate_queryset(goal.contributions.select_related("goal").all(), request, view=self)
        return pager.get_paginated_response(ContributionOutput(page, many=True).data)

    @transaction.atomic
    def post(self, request, pk):
        goal = self.get_goal(pk, lock=True)
        serializer = ContributionInput(data=request.data, context={"goal": goal})
        serializer.is_valid(raise_exception=True)
        values = {key: value for key, value in serializer.validated_data.items() if key != "currency"}
        try:
            entry, created = record_entry(goal, **values)
        except GoalLedgerError as error:
            return Response({"detail": str(error)}, status=status.HTTP_409_CONFLICT)
        return Response({"entry": ContributionOutput(entry).data, "goal": GoalSerializer(goal).data},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class GoalProjectionView(GoalView):
    def get(self, request, pk):
        goal = self.get_goal(pk)
        serializer = ProjectionQuery(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        rate = serializer.validated_data.get("monthly_contribution", goal.monthly_contribution)
        today = timezone.localdate(timezone=account_timezone(request.user))
        return Response(ProjectionOutput(project_goal(goal, today, rate)).data)
