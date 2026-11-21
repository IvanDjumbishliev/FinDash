import re
import unicodedata
from dataclasses import replace
from decimal import Decimal

from django.db import DatabaseError
from rest_framework import serializers
from rest_framework.response import Response

from api.models import GroceryRetailer
from api.services.grocery_basket import BasketLimit, infer_unit, optimize_basket, requested_product
from api.services.grocery_catalog import UNIT, parse_package

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
    overhead_per_store = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal(0), default=Decimal("0.00"),
    )

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
