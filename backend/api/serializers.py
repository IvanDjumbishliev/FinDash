from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from decimal import Decimal

from rest_framework import serializers

from .models import Budget, Subscription, SubscriptionPreferences, Transaction
from .services.budgets import budget_progress, parse_month


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)

    def validate(self, attrs):
        try:
            validate_password(attrs["password"], user=User(username=attrs["username"]))
        except ValidationError as error:
            raise serializers.ValidationError({"password": error.messages}) from None
        return attrs

    class Meta:
        model = User
        fields = ["id", "username", "password"]

    def create(self, validated_data):
        user = User.objects.create_user(**validated_data)
        return user


class TransactionSerializer(serializers.ModelSerializer):
    currency = serializers.RegexField(r"\A[A-Za-z]{3}\Z", default="USD")
    particulars = serializers.CharField(max_length=1024)

    def validate_currency(self, value):
        return value.upper()

    class Meta:
        model = Transaction
        fields = ["id", "amount", "category", "timestamp", "particulars", "currency", "merchant"]
        read_only_fields = ["merchant"]


class SubscriptionSerializer(serializers.ModelSerializer):
    estimated_amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0.01")
    )

    tracking_status = serializers.ChoiceField(choices=Subscription.TrackingStatus.choices, required=False)

    def update(self, instance, validated_data):
        due = validated_data.get("next_expected_payment")
        if due is not None and due != instance.next_expected_payment:
            validated_data["billing_anchor_day"] = due.day
        return super().update(instance, validated_data)

    class Meta:
        model = Subscription
        fields = [
            "id", "owner", "merchant", "normalized_merchant", "estimated_amount",
            "currency", "billing_frequency", "next_expected_payment",
            "detection_confidence", "status", "tracking_status", "billing_anchor_day", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "owner", "normalized_merchant", "currency", "billing_frequency",
            "detection_confidence", "billing_anchor_day", "created_at", "updated_at",
        ]


class SubscriptionPreferencesSerializer(serializers.ModelSerializer):
    reminder_lead_days = serializers.IntegerField(min_value=0, max_value=30, required=False)

    class Meta:
        model = SubscriptionPreferences
        fields = ["renewal_reminders", "reminder_lead_days", "monthly_summary"]


class BudgetSerializer(serializers.ModelSerializer):
    category = serializers.ChoiceField(choices=Transaction.Category.choices, allow_null=True, required=False)
    period = serializers.CharField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))
    currency = serializers.RegexField(r"^[A-Za-z]{3}\Z")
    alert_thresholds = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False)

    def validate_period(self, value):
        try:
            return parse_month(value)
        except ValueError as error:
            raise serializers.ValidationError(str(error)) from error

    def validate_currency(self, value):
        return value.upper()

    def validate_alert_thresholds(self, values):
        if len(set(values)) != len(values):
            raise serializers.ValidationError("Alert thresholds must be distinct.")
        return sorted(values)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["period"] = instance.period.isoformat()
        return {**data, **budget_progress(instance, self.context["spending"])}

    class Meta:
        model = Budget
        fields = [
            "id", "category", "period", "amount", "currency", "alert_thresholds",
            "archived", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
        # Active uniqueness depends on the merged PATCH fields and is enforced in
        # the owner-scoped view and by the database.
        validators = []
