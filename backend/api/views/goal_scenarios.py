from collections.abc import Mapping
from decimal import Decimal

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response

from api.models import GoalScenario
from api.services.copilot_tools import account_timezone
from api.services.goal_scenarios import compare_goal_scenario
from api.services.goals import ZERO

from .goals import GoalView, money

MAX_SAVED_SCENARIOS = 50


class ScenarioChanges(serializers.Serializer):
    monthly_contribution = money(min_value=ZERO, required=False)
    one_time_contribution = money(min_value=ZERO, required=False)
    expense_reduction = money(min_value=ZERO, required=False)
    target_amount = money(min_value=Decimal("0.01"), required=False)
    target_date = serializers.DateField(required=False, allow_null=True)

    def to_internal_value(self, data):
        if isinstance(data, Mapping) and data.keys() - self.fields.keys():
            raise serializers.ValidationError("Unknown scenario change.")
        return super().to_internal_value(data)


class PreviewInput(serializers.Serializer):
    changes = ScenarioChanges()


class SavedGoalScenarioInput(PreviewInput):
    name = serializers.CharField(max_length=80)

    def validate_changes(self, changes):
        if not changes:
            raise serializers.ValidationError("Enter at least one hypothetical change.")
        return changes


class SavedGoalScenarioOutput(serializers.ModelSerializer):
    class Meta:
        model = GoalScenario
        fields = ("id", "name", "changes", "created_at")


class GoalScenarioPreviewView(GoalView):
    def post(self, request, pk):
        goal = self.get_goal(pk)
        serializer = PreviewInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        today = timezone.localdate(timezone=account_timezone(request.user))
        return Response(compare_goal_scenario(goal, today, serializer.validated_data["changes"]))


class GoalScenarioListView(GoalView):
    def get(self, request, pk):
        goal = self.get_goal(pk)
        return Response(SavedGoalScenarioOutput(goal.scenarios.all(), many=True).data)

    @transaction.atomic
    def post(self, request, pk):
        goal = self.get_goal(pk, lock=True)
        serializer = SavedGoalScenarioInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if goal.scenarios.filter(name=data["name"]).exists():
            raise serializers.ValidationError({"name": "A scenario with this name already exists for this goal."})
        if goal.scenarios.count() >= MAX_SAVED_SCENARIOS:
            raise serializers.ValidationError({"name": "Delete a saved scenario before adding another."})
        rendered = ScenarioChanges(instance=data["changes"]).data
        changes = {key: rendered[key] for key in data["changes"]}
        scenario = goal.scenarios.create(name=data["name"], changes=changes)
        return Response(SavedGoalScenarioOutput(scenario).data, status=status.HTTP_201_CREATED)


class GoalScenarioDetailView(GoalView):
    def delete(self, request, pk, scenario_id):
        goal = self.get_goal(pk)
        get_object_or_404(goal.scenarios.all(), pk=scenario_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
