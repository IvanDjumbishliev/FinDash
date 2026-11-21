from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response

from api.models import Notification, NotificationCategory, NotificationPreference, NotificationStockAlert, Stock
from api.services.notifications import MESSAGES, categories_for, retention_cutoff

from .assistant import PrivateCopilotView, StrictBooleanField
from .portfolios import CurrencyField


def owned_notifications(user):
    return Notification.objects.filter(owner=user, created_at__gte=retention_cutoff())


class NotificationOutput(serializers.ModelSerializer):
    read = serializers.SerializerMethodField()
    dismissed = serializers.SerializerMethodField()
    title = serializers.SerializerMethodField()
    message = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ("id", "category", "title", "message", "created_at", "read_at", "dismissed_at", "read", "dismissed")

    def get_read(self, item) -> bool:
        return item.read_at is not None

    def get_dismissed(self, item) -> bool:
        return item.dismissed_at is not None

    def get_title(self, item) -> str:
        return MESSAGES[item.category][0]

    def get_message(self, item) -> str:
        return MESSAGES[item.category][1]


class NotificationPagination(LimitOffsetPagination):
    default_limit = 25
    max_limit = 100


class NotificationFilters(serializers.Serializer):
    unread = serializers.BooleanField(default=False)
    include_dismissed = serializers.BooleanField(default=False)
    category = serializers.ChoiceField(choices=NotificationCategory.values, required=False)


class NotificationListView(PrivateCopilotView):
    def get(self, request):
        query = NotificationFilters(data=request.query_params)
        query.is_valid(raise_exception=True)
        filters = query.validated_data
        owned = owned_notifications(request.user)
        unread_count = owned.filter(read_at__isnull=True, dismissed_at__isnull=True).count()
        rows = owned
        if not filters["include_dismissed"]:
            rows = rows.filter(dismissed_at__isnull=True)
        if filters["unread"]:
            rows = rows.filter(read_at__isnull=True)
        if "category" in filters:
            rows = rows.filter(category=filters["category"])
        pager = NotificationPagination()
        page = pager.paginate_queryset(rows, request, view=self)
        response = pager.get_paginated_response(NotificationOutput(page, many=True).data)
        response.data["unread_count"] = unread_count
        return response


class NotificationPatch(serializers.Serializer):
    read = StrictBooleanField(required=False)
    dismissed = StrictBooleanField(required=False)

    def validate(self, data):
        if not data:
            raise serializers.ValidationError("Supply read or dismissed.")
        return data


class NotificationDetailView(PrivateCopilotView):
    def patch(self, request, pk):
        item = get_object_or_404(owned_notifications(request.user), pk=pk)
        serializer = NotificationPatch(data=request.data)
        serializer.is_valid(raise_exception=True)
        now = timezone.now()
        values = {}
        for key, enabled in serializer.validated_data.items():
            field = f"{key}_at"
            existing = getattr(item, field)
            values[field] = (existing or now) if enabled else None
        Notification.objects.filter(pk=item.pk, owner=request.user).update(**values)
        for key, value in values.items():
            setattr(item, key, value)
        return Response(NotificationOutput(item).data)


class NotificationMarkAllReadView(PrivateCopilotView):
    def post(self, request):
        count = owned_notifications(request.user).filter(
            read_at__isnull=True, dismissed_at__isnull=True,
        ).update(read_at=timezone.now())
        return Response({"updated": count})


class StockAlertSerializer(serializers.ModelSerializer):
    currency = CurrencyField()
    ticker = serializers.RegexField(r"\A[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*\Z", max_length=10)
    target = serializers.DecimalField(max_digits=18, decimal_places=8, min_value=Decimal("0.00000001"))

    class Meta:
        model = NotificationStockAlert
        fields = ("ticker", "currency", "direction", "target")

    def validate_ticker(self, ticker):
        return ticker.upper()


class PreferencesPatch(serializers.Serializer):
    categories = serializers.DictField(child=StrictBooleanField(), required=False)
    stock_alerts = StockAlertSerializer(many=True, max_length=10, required=False)

    def validate_categories(self, categories):
        if categories.keys() - set(NotificationCategory.values):
            raise serializers.ValidationError("Unknown notification category.")
        return categories

    def validate_stock_alerts(self, alerts):
        symbols = {rule["ticker"] for rule in alerts}
        watchlist = set(Stock.objects.filter(user=self.context["user"], ticker__in=symbols).values_list("ticker", flat=True))
        if symbols - watchlist:
            raise serializers.ValidationError("Each price alert needs a ticker on your watchlist.")
        keys = {tuple(rule[field] for field in StockAlertSerializer.Meta.fields) for rule in alerts}
        if len(keys) != len(alerts):
            raise serializers.ValidationError("Remove duplicate price alerts.")
        return alerts


class NotificationPreferencesView(PrivateCopilotView):
    def get(self, request):
        return self.output(request.user)

    def patch(self, request):
        serializer = PreferencesPatch(data=request.data, context={"user": request.user})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        with transaction.atomic():
            owner = get_user_model().objects.select_for_update().get(pk=request.user.pk)
            if "categories" in data:
                preferences, _ = NotificationPreference.objects.get_or_create(owner=owner)
                preferences.categories = {**preferences.categories, **data["categories"]}
                preferences.save(update_fields=["categories"])
            if "stock_alerts" in data:
                rules = NotificationStockAlert.objects.filter(owner=owner)
                ids = [rules.get_or_create(owner=owner, **alert)[0].pk for alert in data["stock_alerts"]]
                rules.exclude(pk__in=ids).delete()
        return self.output(request.user)

    @staticmethod
    def output(user):
        rules = NotificationStockAlert.objects.filter(owner=user).order_by("ticker", "currency", "direction", "target")
        return Response({"categories": categories_for(user.pk), "stock_alerts": StockAlertSerializer(rules, many=True).data})
