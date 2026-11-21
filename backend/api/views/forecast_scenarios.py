from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import DatabaseError, IntegrityError, transaction
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from api.models import CashFlowScenario, Transaction
from api.services.forecast_scenarios import compare_scenario
from api.services.forecasting import ForecastDataLimit, build_cash_flow_forecast

from .assistant import PrivateCopilotView
from .forecast import ForecastQuery

MAX_SAVED_SCENARIOS = 50


class CashChange(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    day = serializers.IntegerField(min_value=1, max_value=90, default=1)


class RecurringExpense(CashChange):
    frequency = serializers.ChoiceField(choices=("weekly", "monthly"), default="monthly")


class CategoryReduction(serializers.Serializer):
    category = serializers.ChoiceField(choices=Transaction.Category.values)
    percent = serializers.IntegerField(min_value=1, max_value=100)


class Changes(serializers.Serializer):
    monthly_income = CashChange(required=False)
    spending_reduction = CategoryReduction(required=False)
    recurring_expense = RecurringExpense(required=False)
    remove_subscription_id = serializers.IntegerField(min_value=1, max_value=2**63 - 1, required=False)
    purchase = CashChange(required=False)
    starting_balance = serializers.DecimalField(max_digits=14, decimal_places=2, required=False)


class ScenarioPreviewInput(ForecastQuery):
    changes = Changes()

    def validate(self, data):
        if not data["changes"]:
            raise serializers.ValidationError({"changes": "Enter at least one hypothetical change."})
        return data


class CashFlowScenarioPreviewView(PrivateCopilotView):
    def post(self, request):
        serializer = ScenarioPreviewInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        options = serializer.validated_data.copy()
        changes = options.pop("changes")
        try:
            baseline = build_cash_flow_forecast(request.user, include_uncertainty=False, **options)
        except ForecastDataLimit:
            return Response({"error": "Recorded activity exceeds the forecast processing limit."}, status=422)
        except DatabaseError:
            return Response({"error": "The forecast is temporarily unavailable."}, status=503)

        return Response(compare_scenario(baseline, changes))


class SavedScenarioInput(ForecastQuery):
    name = serializers.CharField(max_length=80)
    starting_balance = None
    currency = serializers.RegexField(r"\A[A-Za-z]{3}\Z")
    changes = Changes()

    def validate_changes(self, changes):
        if not changes:
            raise serializers.ValidationError("Enter at least one hypothetical change.")
        return changes


class SavedScenarioOutput(serializers.ModelSerializer):
    class Meta:
        model = CashFlowScenario
        fields = ("id", "name", "horizon", "currency", "changes", "created_at")


class CashFlowScenarioListView(PrivateCopilotView):
    def get(self, request):
        rows = CashFlowScenario.objects.filter(owner=request.user)
        return Response(SavedScenarioOutput(rows, many=True).data)

    def post(self, request):
        serializer = SavedScenarioInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data.copy()
        data["changes"] = Changes(instance=data["changes"]).data
        try:
            with transaction.atomic():
                owner = get_user_model().objects.select_for_update().get(pk=request.user.pk)
                if CashFlowScenario.objects.filter(owner=owner).count() >= MAX_SAVED_SCENARIOS:
                    raise ValidationError({"name": "Delete a saved scenario before adding another."})
                scenario = CashFlowScenario.objects.create(owner=owner, **data)
        except IntegrityError as error:
            raise ValidationError({"name": "A scenario with this name already exists."}) from error
        return Response(SavedScenarioOutput(scenario).data, status=201)


class CashFlowScenarioDetailView(PrivateCopilotView):
    def delete(self, request, pk):
        deleted, _ = CashFlowScenario.objects.filter(owner=request.user, pk=pk).delete()
        if not deleted:
            return Response({"error": "Scenario not found."}, status=404)
        return Response(status=204)
