from django.contrib.auth.models import User
from decimal import Decimal

from rest_framework import serializers

from .models import Subscription, SubscriptionPreferences, Transaction


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "password"]
        extra_kwargs = {"password": {"write_only": True}}

    def create(self, validated_data):
        user = User.objects.create_user(**validated_data)
        return user


class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = ["id", "amount", "category", "timestamp", "particulars", "currency"]


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
