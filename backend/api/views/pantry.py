from decimal import Decimal

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from api.models import GroceryOffer, PantryItem, ProductPreference, Receipt, ReceiptItem
from api.services.grocery_catalog import normalized
from api.services.grocery_matching import describe
from api.services.personalized_deals import MAX_OFFERS, assess, catalog_status, current_offers, interest_product
from api.throttles import SensitiveEndpointThrottle

from .assistant import PrivateCopilotView, StrictBooleanField
from .grocery import CatalogPackageSerializer, catalog_package
from .personalized_deals import CatalogStatusSerializer


def measurement(**options):
    return serializers.DecimalField(
        max_digits=13, decimal_places=6, min_value=Decimal(0), max_value=Decimal(1000),
        required=False, allow_null=True, **options,
    )


class PantrySerializer(serializers.ModelSerializer):
    quantity = measurement()
    replenish_below = measurement()
    track_deals = StrictBooleanField(required=False)
    quantity_confirmed = StrictBooleanField(required=False)
    needs_replenishment = serializers.SerializerMethodField()

    class Meta:
        model = PantryItem
        fields = ("id", "receipt_item", "product", "name", "brand", "quantity", "unit",
                  "quantity_confirmed", "expires_on", "replenish_below", "track_deals", "needs_replenishment")
        read_only_fields = ("receipt_item", "product")

    def get_needs_replenishment(self, item) -> bool:
        return (item.quantity is not None and item.replenish_below is not None
                and item.quantity <= item.replenish_below)

    def validate_name(self, value):
        if not normalized(value) or not value.isprintable():
            raise serializers.ValidationError("Enter a product name.")
        return value

    def validate(self, attrs):
        def value(key, default=None):
            return attrs.get(key, getattr(self.instance, key, default))

        quantity = value("quantity")
        unit = value("unit", "")
        if self.instance and "unit" in attrs and unit != self.instance.unit:
            if self.instance.quantity is not None and "quantity" not in attrs:
                raise serializers.ValidationError({"quantity": "Enter the quantity in the new unit."})
            attrs.setdefault("replenish_below", None)
        threshold = value("replenish_below")
        if (quantity is not None or threshold is not None) and not unit:
            raise serializers.ValidationError({"unit": "Choose a unit for this quantity."})
        if unit == "item" and any(v is not None and v != v.to_integral_value() for v in (quantity, threshold)):
            raise serializers.ValidationError({"quantity": "Use whole numbers for item counts."})
        if {"quantity", "unit"} & attrs.keys():
            attrs.setdefault("quantity_confirmed", False)
        if attrs.get("quantity_confirmed") and quantity is None:
            raise serializers.ValidationError({"quantity": "Enter a quantity to confirm it."})
        if self.instance and {"name", "brand"} & attrs.keys() and (
            value("name") != self.instance.name or value("brand") != self.instance.brand
        ):
            attrs["product"] = None
        return attrs


class PantryPagination(PageNumberPagination):
    page_size = 24


class PantryScope(PrivateCopilotView):
    serializer_class = PantrySerializer

    def get_queryset(self):
        return PantryItem.objects.filter(owner=self.request.user)


class PantryList(PantryScope, generics.ListCreateAPIView):
    pagination_class = PantryPagination

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class PantryDetail(PantryScope, generics.RetrieveUpdateDestroyAPIView):
    http_method_names = ["get", "patch", "delete", "head", "options"]


class PantryReceiptInput(serializers.Serializer):
    receipt_item = serializers.IntegerField(min_value=1, max_value=2**63 - 1)


class PantryReceiptAdd(PrivateCopilotView):
    @extend_schema(request=PantryReceiptInput, responses={200: PantrySerializer, 201: PantrySerializer})
    def post(self, request):
        form = PantryReceiptInput(data=request.data)
        form.is_valid(raise_exception=True)
        row = get_object_or_404(
            ReceiptItem, pk=form.validated_data["receipt_item"],
            receipt__owner=request.user, receipt__status=Receipt.Status.CONFIRMED,
        )
        if row.line_total < 0 or (row.quantity is not None and row.quantity <= 0):
            raise serializers.ValidationError("A refund or reversal cannot be added to pantry inventory.")
        quantity = row.quantity if row.unit else None
        if quantity is not None and (quantity > 1000 or (row.unit == "item" and quantity % 1)):
            quantity = None
        item, created = PantryItem.objects.get_or_create(owner=request.user, receipt_item=row, defaults={
            "name": row.original_description[:180], "brand": row.brand, "product_id": row.product_id,
            "quantity": quantity, "unit": row.unit, "quantity_confirmed": False,
        })
        return Response(PantrySerializer(item).data, status=201 if created else 200)


class PantryDealSerializer(serializers.Serializer):
    package = CatalogPackageSerializer()
    relation = serializers.ChoiceField(choices=["exact", "comparable"])


class PantryDealsSerializer(serializers.Serializer):
    offers = PantryDealSerializer(many=True)
    retailers = CatalogStatusSerializer(many=True)
    catalog_truncated = serializers.BooleanField()


class PantryDeals(PrivateCopilotView):
    throttle_classes = [SensitiveEndpointThrottle]
    throttle_scope = "pantry_deals"

    @extend_schema(responses=PantryDealsSerializer)
    def get(self, request, pk):
        item = get_object_or_404(PantryItem.objects.select_related("product"), owner=request.user, pk=pk)
        if not item.track_deals:
            raise serializers.ValidationError("Enable deal tracking for this pantry item first.")
        now = timezone.now()
        preference = ProductPreference(name=item.name, preferred_brand=item.brand, preferred_unit=item.unit,
                                       product=item.product)
        target = interest_product(preference)
        offers = list(current_offers(currency="EUR", membership_retailers=[], now=now)
                      .filter(unit_price__isnull=False, quantity__isnull=False)
                      .order_by("-last_successful_update", "pk")[:MAX_OFFERS + 1])
        matches = []
        for offer in offers[:MAX_OFFERS]:
            product = describe(offer)
            if target.title != product.title and (not target.category or target.category != product.category):
                continue
            match = assess(preference, target, offer, product)
            if match and match[0] != "needs_review" and (not item.brand or match[2]):
                matches.append((offer, product, match))
        matches.sort(key=lambda pair: (pair[2][0] != "exact", -pair[2][1], pair[0].expires_on, pair[0].pk))
        return Response({
            "offers": [{"package": CatalogPackageSerializer(catalog_package(offer, product)).data, "relation": match[0]}
                       for offer, product, match in matches[:12]],
            "retailers": CatalogStatusSerializer(catalog_status(now), many=True).data,
            "catalog_truncated": len(offers) > MAX_OFFERS,
        })


class PantryRecipeSerializer(serializers.Serializer):
    name = serializers.CharField()
    ingredients = serializers.ListField(child=serializers.CharField())


class PantryRecipes(PrivateCopilotView):
    @extend_schema(responses=PantryRecipeSerializer(many=True))
    def get(self, request):
        rows = PantryItem.objects.filter(owner=request.user, quantity_confirmed=True, quantity__gt=0)
        available = {}
        for name, brand in rows.values_list("name", "brand").iterator():
            product = describe(GroceryOffer(product_name=name, brand=brand))
            if product.category and not product.ambiguous:
                available.setdefault(product.category, name)
        recipes = (
            ("Cheese omelette", ("eggs", "cheese")),
            ("Buttered pasta with cheese", ("pasta", "butter", "cheese")),
            ("Buttered rice", ("rice", "butter")),
            ("Cheese toast", ("bread", "cheese")),
        )
        return Response(PantryRecipeSerializer([
            {"name": name, "ingredients": [available[ingredient] for ingredient in ingredients]}
            for name, ingredients in recipes if all(ingredient in available for ingredient in ingredients)
        ], many=True).data)
