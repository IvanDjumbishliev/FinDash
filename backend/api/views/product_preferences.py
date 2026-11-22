from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from api.models import GroceryOffer, GroceryRetailer, ProductPreference, ShoppingPersonalization
from api.services.product_preferences import CATEGORY_LABELS, LIBRARY_LIMIT, LOOKBACK_DAYS, available_offers, purchase_signals, suggested_products
from api.services.receipts import product_identity

from .assistant import PrivateCopilotView, StrictBooleanField


class ProductSettingsSerializer(serializers.ModelSerializer):
    automatic_enabled = StrictBooleanField(required=False)
    preferred_retailers = serializers.ListField(
        child=serializers.ChoiceField(choices=GroceryRetailer.choices), max_length=len(GroceryRetailer.values), required=False,
    )
    category_interests = serializers.ListField(
        child=serializers.ChoiceField(choices=list(CATEGORY_LABELS.items())), max_length=len(CATEGORY_LABELS), required=False,
    )

    class Meta:
        model = ShoppingPersonalization
        fields = ("automatic_enabled", "preferred_retailers", "category_interests")

    def validate(self, attrs):
        return {key: list(dict.fromkeys(value)) if isinstance(value, list) else value for key, value in attrs.items()}


class ProductPreferenceSerializer(serializers.ModelSerializer):
    name = serializers.CharField(max_length=255, required=False)
    preferred_quantity = serializers.DecimalField(
        max_digits=14, decimal_places=6, min_value=Decimal("0.000001"), allow_null=True, required=False,
    )
    minimum_discount = serializers.IntegerField(min_value=0, max_value=100, allow_null=True, required=False)
    favorite = StrictBooleanField(required=False)
    notifications_enabled = StrictBooleanField(required=False)
    excluded = StrictBooleanField(required=False)
    muted = StrictBooleanField(required=False)

    class Meta:
        model = ProductPreference
        fields = (
            "id", "product", "name", "normalized_name", "source", "favorite", "preferred_brand",
            "preferred_quantity", "preferred_unit", "minimum_discount", "notifications_enabled",
            "excluded", "muted", "last_purchase_date", "purchase_frequency", "last_notified_offer",
        )
        read_only_fields = ("id", "normalized_name", "source", "last_purchase_date", "purchase_frequency", "last_notified_offer")

    def validate(self, attrs):
        if not self.instance:
            product = attrs.get("product")
            name = attrs.get("name") or (product.product_name if product else "")
            identity = product_identity(product.normalized_name or product.product_name) if product else product_identity(name)
            if not identity or not name.isprintable():
                raise ValidationError({"name": "Enter a product name or choose a catalog product."})
            attrs["name"] = product.product_name if product else name
            attrs["normalized_name"] = identity
        elif {"name", "product"} & attrs.keys():
            raise ValidationError({"name": "Add a new preference to follow a different product."})

        quantity = attrs.get("preferred_quantity", getattr(self.instance, "preferred_quantity", None))
        unit = attrs.get("preferred_unit", getattr(self.instance, "preferred_unit", ""))
        if (quantity is None) != (not unit):
            raise ValidationError({"preferred_unit": "Enter both a package quantity and unit, or clear both."})
        if unit == GroceryOffer.Unit.ITEM and quantity != quantity.to_integral_value():
            raise ValidationError({"preferred_quantity": "Package item counts must be whole numbers."})
        return attrs


class ProductOfferSerializer(serializers.ModelSerializer):
    class Meta:
        model = GroceryOffer
        fields = ("id", "product_name", "normalized_name", "retailer", "brand", "price", "currency", "quantity",
                  "measurement_unit", "discount_percent", "expires_on", "requires_membership")


class ProductSuggestionSerializer(serializers.Serializer):
    name = serializers.CharField()
    normalized_name = serializers.CharField()
    category = serializers.CharField()
    purchase_frequency = serializers.IntegerField()
    last_purchase_date = serializers.DateField()


class ProductLibrarySerializer(serializers.Serializer):
    settings = ProductSettingsSerializer()
    products = ProductPreferenceSerializer(many=True)
    suggestions = ProductSuggestionSerializer(many=True)
    offers = ProductOfferSerializer(many=True)
    categories = serializers.DictField(child=serializers.CharField())
    retailers = serializers.DictField(child=serializers.CharField())
    lookback_days = serializers.IntegerField()


class SuggestionDecisionSerializer(serializers.Serializer):
    normalized_name = serializers.CharField(max_length=255)
    decision = serializers.ChoiceField(choices=["approve", "reject"])


def lock_owner(user):
    get_user_model().objects.select_for_update().only("pk").get(pk=user.pk)


def product_settings(owner):
    return ShoppingPersonalization.objects.filter(owner=owner).first() or ShoppingPersonalization(owner=owner)


def products_for(owner):
    return ProductPreference.objects.filter(owner=owner)


def ensure_space(queryset):
    if queryset.count() >= LIBRARY_LIMIT:
        raise ValidationError("Your product library is full. Remove a preference before adding another.")


class ProductLibraryView(PrivateCopilotView):
    @extend_schema(responses=ProductLibrarySerializer)
    def get(self, request):
        settings = product_settings(request.user)
        products = list(products_for(request.user))
        signals = list(purchase_signals(request.user)) if settings.automatic_enabled else []
        signal_map = {row["normalized_name"]: row for row in signals}
        if settings.automatic_enabled:
            for product in products:
                signal = signal_map.get(product.normalized_name, {})
                product.purchase_frequency = signal.get("purchase_frequency", 0)
                product.last_purchase_date = signal.get("last_purchase_date")
        suggestions = suggested_products(signals, {row.normalized_name for row in products})
        return Response(ProductLibrarySerializer({
            "settings": settings, "products": products, "suggestions": suggestions,
            "offers": available_offers(products, settings), "categories": CATEGORY_LABELS,
            "retailers": dict(GroceryRetailer.choices), "lookback_days": LOOKBACK_DAYS,
        }).data)

    @extend_schema(request=ProductPreferenceSerializer, responses={201: ProductPreferenceSerializer})
    @transaction.atomic
    def post(self, request):
        form = ProductPreferenceSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        lock_owner(request.user)
        products = products_for(request.user)
        if products.filter(normalized_name=form.validated_data["normalized_name"]).exists():
            raise ValidationError({"name": "This product already exists in your library."})
        ensure_space(products)
        return Response(ProductPreferenceSerializer(form.save(owner=request.user)).data, status=201)


class ProductPreferenceDetailView(PrivateCopilotView):
    @extend_schema(request=ProductPreferenceSerializer, responses=ProductPreferenceSerializer)
    @transaction.atomic
    def patch(self, request, pk):
        lock_owner(request.user)
        preference = get_object_or_404(products_for(request.user).select_for_update(), pk=pk)
        form = ProductPreferenceSerializer(preference, data=request.data, partial=True)
        form.is_valid(raise_exception=True)
        return Response(ProductPreferenceSerializer(form.save()).data)

    @extend_schema(responses={204: None})
    @transaction.atomic
    def delete(self, request, pk):
        lock_owner(request.user)
        get_object_or_404(products_for(request.user), pk=pk).delete()
        return Response(status=204)


class ProductSettingsView(PrivateCopilotView):
    @extend_schema(request=ProductSettingsSerializer, responses=ProductSettingsSerializer)
    @transaction.atomic
    def patch(self, request):
        lock_owner(request.user)
        settings, _ = ShoppingPersonalization.objects.get_or_create(owner=request.user)
        form = ProductSettingsSerializer(settings, data=request.data, partial=True)
        form.is_valid(raise_exception=True)
        return Response(ProductSettingsSerializer(form.save()).data)


class ProductSuggestionView(PrivateCopilotView):
    @extend_schema(request=SuggestionDecisionSerializer, responses=ProductPreferenceSerializer)
    @transaction.atomic
    def post(self, request):
        form = SuggestionDecisionSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        lock_owner(request.user)
        if not product_settings(request.user).automatic_enabled:
            raise PermissionDenied("Enable receipt-based personalization before reviewing suggestions.")
        products = products_for(request.user)
        identity = form.validated_data["normalized_name"]
        suggestions = suggested_products(purchase_signals(request.user), set(products.values_list("normalized_name", flat=True)))
        row = next((item for item in suggestions if item["normalized_name"] == identity), None)
        if row is None:
            raise ValidationError({"normalized_name": "This suggestion is no longer available."})
        ensure_space(products)
        rejected = form.validated_data["decision"] == "reject"
        preference = products.create(
            owner=request.user, name=row["name"], normalized_name=identity, source=ProductPreference.Source.INFERRED,
            favorite=not rejected, excluded=rejected, purchase_frequency=row["purchase_frequency"],
            last_purchase_date=row["last_purchase_date"],
        )
        return Response(ProductPreferenceSerializer(preference).data)

    @extend_schema(responses={204: None})
    @transaction.atomic
    def delete(self, request):
        lock_owner(request.user)
        products_for(request.user).filter(source=ProductPreference.Source.INFERRED).delete()
        return Response(status=204)
