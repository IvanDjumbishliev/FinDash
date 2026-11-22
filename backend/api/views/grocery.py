import re
import unicodedata
from dataclasses import replace
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import DatabaseError, IntegrityError, transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response

from api.throttles import SensitiveEndpointThrottle
from api.models import GroceryOffer, GroceryRetailer, GroceryShoppingList
from api.services.grocery_basket import BasketLimit, infer_unit, optimize_basket, requested_product
from api.services.grocery_catalog import UNIT, normalized, parse_package
from api.services.grocery_matching import describe

from .assistant import PrivateCopilotView, StrictBooleanField


class ShoppingListItem(serializers.Serializer):
    name = serializers.CharField(max_length=180)
    quantity = serializers.DecimalField(
        max_digits=13, decimal_places=6, min_value=Decimal("0.000001"), max_value=Decimal("1000000"),
    )
    unit = serializers.CharField(max_length=24, required=False)
    preferred_brand = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    allow_substitutions = StrictBooleanField(default=True)

    def validate(self, data):
        product = requested_product(data["name"], data["preferred_brand"])
        if not product.title or product.ambiguous:
            raise serializers.ValidationError({"name": "Use a product title with an unambiguous package description."})
        named_package = product.quantity
        named_pack_count = product.pack_count
        quantity = data["quantity"]
        unit = infer_unit(product)
        if "unit" in data:
            value = unicodedata.normalize("NFKC", data["unit"]).casefold()
            if value == "item":
                value = "pc"
            if not re.fullmatch(rf"(?:{UNIT})\.?", value):
                raise serializers.ValidationError({"unit": "Use kilograms, grams, liters, milliliters, or items."})
            package = parse_package(f"{quantity:f} {value}")
            if not package:
                raise serializers.ValidationError({"quantity": "This amount is invalid for the selected unit."})
            quantity, unit, _, _ = package
        if unit is None:
            raise serializers.ValidationError({"unit": "Specify the unit for this product."})
        if product.unit and product.unit != unit:
            raise serializers.ValidationError({"unit": "The unit conflicts with the package in the product name."})
        if quantity > 1000:
            raise serializers.ValidationError({"quantity": "Use at most 1,000 kg, liters, or items per line."})
        if unit == "item" and quantity != quantity.to_integral_value():
            raise serializers.ValidationError({"quantity": "Item counts must be whole numbers."})
        return {
            **data, "quantity": quantity, "named_package": named_package, "named_pack_count": named_pack_count,
            "product": replace(product, quantity=named_package or Decimal(1), unit=unit),
        }


class GroceryBasketInput(serializers.Serializer):
    items = ShoppingListItem(many=True, allow_empty=False, max_length=40)
    currency = serializers.ChoiceField(choices=("EUR", "BGN"), default="EUR")
    allow_multi_store = StrictBooleanField(default=True)
    max_stores = serializers.IntegerField(min_value=1, max_value=len(GroceryRetailer.values), default=3)
    retailers = serializers.ListField(
        child=serializers.ChoiceField(choices=GroceryRetailer.values),
        allow_empty=False, max_length=len(GroceryRetailer.values), default=list(GroceryRetailer.values),
    )
    overhead_per_store = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal(0), default=Decimal("0.00"),
    )

    def validate_retailers(self, retailers):
        if len(set(retailers)) != len(retailers):
            raise serializers.ValidationError("Select each retailer once.")
        return retailers

    def validate_items(self, items):
        seen = set()
        for item in items:
            product = item["product"]
            key = (product.title, product.traits, product.brand, product.unit, item["allow_substitutions"],
                   item["named_package"], item["named_pack_count"])
            if key in seen:
                raise serializers.ValidationError("Combine duplicate shopping-list lines into one quantity.")
            seen.add(key)
        return items


class GroceryOptimizeView(PrivateCopilotView):
    throttle_classes = [SensitiveEndpointThrottle]
    throttle_scope = "grocery_optimize"

    def post(self, request):
        serializer = GroceryBasketInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = optimize_basket(**serializer.validated_data)
        except BasketLimit as error:
            return Response({"error": str(error)}, status=422)
        except DatabaseError:
            return Response({"error": "The grocery catalog is temporarily unavailable."}, status=503)
        return Response(result)


class GroceryCatalogQuery(serializers.Serializer):
    q = serializers.CharField(min_length=2, max_length=100)
    retailers = serializers.CharField(required=False, max_length=32)

    def validate_retailers(self, value):
        selected = value.split(",")
        if any(key not in GroceryRetailer.values for key in selected):
            raise serializers.ValidationError("Choose supported retailers.")
        return selected

    currency = serializers.ChoiceField(choices=("EUR", "BGN"), default="EUR")



class CatalogPackageSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    brand = serializers.CharField(allow_blank=True)
    retailer = serializers.ChoiceField(choices=GroceryRetailer.choices)
    quantity = serializers.CharField()
    unit = serializers.ChoiceField(choices=GroceryOffer.Unit.choices)
    image_url = serializers.CharField(allow_blank=True)
    price = serializers.CharField()
    currency = serializers.ChoiceField(choices=["EUR", "BGN"])
    expires_on = serializers.DateField()
    last_successful_update = serializers.DateTimeField()


def catalog_package(offer, product):
    return {
        "id": offer.pk, "name": offer.product_name, "brand": offer.brand,
        "retailer": offer.retailer, "quantity": format(product.quantity.normalize(), "f"),
        "unit": product.unit, "image_url": offer.image_url, "price": str(offer.price),
        "currency": offer.currency, "expires_on": offer.expires_on,
        "last_successful_update": offer.last_successful_update,
    }


class GroceryCatalogDetailView(PrivateCopilotView):
    @extend_schema(responses=CatalogPackageSerializer)
    def get(self, request, pk):
        offer = get_object_or_404(
            GroceryOffer.objects.current(), pk=pk, retailer__in=GroceryRetailer.values,
            requires_membership=False, availability_status="advertised", currency__in=("EUR", "BGN"), price__gt=0,
        )
        product = describe(offer)
        if product.ambiguous or not product.unit or not product.quantity or product.quantity > 1000 or len(offer.product_name) > 180:
            raise serializers.ValidationError({"detail": "This package cannot be added to a shopping list."})
        return Response(CatalogPackageSerializer(catalog_package(offer, product)).data)


class GroceryCatalogView(PrivateCopilotView):
    def get(self, request):
        serializer = GroceryCatalogQuery(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        query = serializer.validated_data
        term = normalized(query["q"])
        if not term:
            return Response([])
        family = requested_product(query["q"]).category
        offers = GroceryOffer.objects.current().filter(
            currency=query["currency"], retailer__in=query.get("retailers", GroceryRetailer.values),
            requires_membership=False, availability_status="advertised",
        )
        suggestions = []
        for offer in offers.order_by("-last_successful_update", "pk")[:6000].iterator():
            product = describe(offer)
            if (term not in offer.normalized_name and term not in normalized(offer.product_name)
                    and term not in product.brand and term != product.title
                    and not (family and product.category == family and term == family)):
                continue
            if product.ambiguous or not product.quantity or not product.unit:
                continue
            suggestions.append(catalog_package(offer, product))
            if len(suggestions) == 12:
                break
        return Response(suggestions)


class ShoppingListInput(GroceryBasketInput):
    name = serializers.CharField(max_length=80)


class ShoppingListOutput(serializers.ModelSerializer):
    class Meta:
        model = GroceryShoppingList
        fields = ("id", "name", "settings", "created_at")


class GroceryShoppingListView(PrivateCopilotView):
    def get(self, request):
        records = GroceryShoppingList.objects.filter(owner=request.user)
        return Response(ShoppingListOutput(records, many=True).data)

    def post(self, request):
        serializer = ShoppingListInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data.copy()
        name = data.pop("name")
        data["overhead_per_store"] = str(data["overhead_per_store"])
        data["max_stores"] = min(data["max_stores"], len(data["retailers"]))
        data["items"] = [
            {
                "name": row["name"], "quantity": format(row["quantity"], "f"), "unit": row["product"].unit,
                "preferred_brand": row["preferred_brand"], "allow_substitutions": row["allow_substitutions"],
            }
            for row in data["items"]
        ]
        try:
            with transaction.atomic():
                owner = get_user_model().objects.select_for_update().get(pk=request.user.pk)
                if GroceryShoppingList.objects.filter(owner=owner).count() >= 50:
                    return Response({"name": ["Delete a saved list before adding another."]}, status=400)
                record = GroceryShoppingList.objects.create(owner=owner, name=name, settings=data)
        except IntegrityError:
            return Response({"name": ["A shopping list with this name already exists."]}, status=400)
        return Response(ShoppingListOutput(record).data, status=201)


class GroceryShoppingListDetailView(PrivateCopilotView):
    def delete(self, request, pk):
        deleted, _ = GroceryShoppingList.objects.filter(owner=request.user, pk=pk).delete()
        if not deleted:
            return Response({"error": "Shopping list not found."}, status=404)
        return Response(status=204)
