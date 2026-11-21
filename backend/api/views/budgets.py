from itertools import groupby

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import generics, serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from api.models import Budget
from api.serializers import BudgetSerializer
from api.services.budgets import parse_month, spending_by_budget

DUPLICATE_BUDGET = "An active budget already exists for this category and month."


class BudgetView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = BudgetSerializer

    def get_queryset(self):
        return Budget.objects.filter(owner=self.request.user)

    def period_param(self, default=None):
        value = self.request.query_params.get("period")
        if value is None:
            return default
        try:
            return parse_month(value)
        except ValueError as error:
            raise serializers.ValidationError({"period": str(error)}) from error

    def serialize_budgets(self, budgets):
        return self.get_serializer(
            budgets, many=True,
            context={**self.get_serializer_context(), "spending": spending_by_budget(self.request.user, budgets)},
        ).data

    def save_budget(self, serializer):
        instance = serializer.instance
        data = serializer.validated_data

        def value(field, default=None):
            return data.get(field, getattr(instance, field, default))

        duplicates = self.get_queryset().filter(period=value("period"), category=value("category"), archived=False)
        if instance is not None:
            duplicates = duplicates.exclude(pk=instance.pk)
        active = not value("archived", False)
        if active and duplicates.exists():
            raise serializers.ValidationError({"non_field_errors": [DUPLICATE_BUDGET]})

        try:
            with transaction.atomic():
                serializer.save(owner=self.request.user)
        except IntegrityError as error:
            if active and duplicates.exists():
                raise serializers.ValidationError({"non_field_errors": [DUPLICATE_BUDGET]}) from error
            raise
        serializer.context["spending"] = spending_by_budget(self.request.user, [serializer.instance])


class BudgetListView(generics.ListCreateAPIView, BudgetView):
    def list(self, request, *args, **kwargs):
        budgets = self.get_queryset()
        period = self.period_param()
        if period is not None:
            budgets = budgets.filter(period=period)
        return Response(self.serialize_budgets(list(budgets)))

    def perform_create(self, serializer):
        self.save_budget(serializer)


class BudgetDetailView(generics.RetrieveUpdateDestroyAPIView, BudgetView):
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def retrieve(self, request, *args, **kwargs):
        return Response(self.serialize_budgets([self.get_object()])[0])

    def perform_update(self, serializer):
        self.save_budget(serializer)


class BudgetOverviewView(BudgetView):
    def get(self, request):
        period = self.period_param(default=timezone.localdate().replace(day=1))
        budgets = list(self.get_queryset().filter(period=period, archived=False))
        result = self.serialize_budgets(budgets)
        return Response({
            "period": period.isoformat(),
            "overall": next((item for item in result if item["category"] is None), None),
            "budgets": [item for item in result if item["category"] is not None],
        })


class BudgetHistoryView(BudgetView):
    def get(self, request):
        budgets = list(self.get_queryset())
        result = self.serialize_budgets(budgets)
        return Response({
            "periods": [
                {"period": period, "budgets": list(items)}
                for period, items in groupby(result, key=lambda item: item["period"])
            ],
        })
