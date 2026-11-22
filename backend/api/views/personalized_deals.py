from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from api.models import GroceryOffer, GroceryRetailer, PersonalizedOfferReview, ProductPreference
from api.services.grocery_matching import describe
from api.services.personalized_deals import assess, discount_met, input_signature, interest_product, personalize

from .assistant import PrivateCopilotView
from .product_preferences import product_settings


class PersonalizedDealsQuery(serializers.Serializer):
    currency = serializers.ChoiceField(choices=["EUR", "BGN"], default="EUR")
    membership_retailers = serializers.ListField(
        child=serializers.ChoiceField(choices=GroceryRetailer.choices),
        max_length=len(GroceryRetailer.values), default=list,
    )
    include_review = serializers.BooleanField(default=False)


class HistoricalPriceSerializer(serializers.Serializer):
    unit_price = serializers.DecimalField(max_digits=24, decimal_places=6)
    purchased_at = serializers.DateTimeField()


class PersonalizedOfferSerializer(serializers.Serializer):
    offer_id = serializers.IntegerField()
    product_name = serializers.CharField()
    retailer = serializers.ChoiceField(choices=GroceryRetailer.choices)
    brand = serializers.CharField(allow_blank=True)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=6)
    unit = serializers.ChoiceField(choices=GroceryOffer.Unit.choices)
    price = serializers.DecimalField(max_digits=12, decimal_places=2)
    unit_price = serializers.DecimalField(max_digits=24, decimal_places=6)
    currency = serializers.ChoiceField(choices=["EUR", "BGN"])
    requires_membership = serializers.BooleanField()
    expires_on = serializers.DateField()
    observed_at = serializers.DateTimeField()
    relation = serializers.ChoiceField(choices=["exact", "comparable", "needs_review"])
    confidence = serializers.DecimalField(max_digits=4, decimal_places=3)
    brand_match = serializers.BooleanField()
    quantity_match = serializers.BooleanField()
    user_reviewed = serializers.BooleanField()
    discount_percent = serializers.IntegerField(allow_null=True)
    historical = HistoricalPriceSerializer(allow_null=True)


class PersonalizedInterestSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    source = serializers.ChoiceField(choices=ProductPreference.Source.choices)
    favorite = serializers.BooleanField()
    matches = PersonalizedOfferSerializer(many=True)
    review = PersonalizedOfferSerializer(many=True)


class PersonalizedDealsSerializer(serializers.Serializer):
    interests = PersonalizedInterestSerializer(many=True)
    catalog_truncated = serializers.BooleanField()


class PersonalizedReviewSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=PersonalizedOfferReview.Decision.choices)


class PersonalizedDealsView(PrivateCopilotView):
    @extend_schema(parameters=[PersonalizedDealsQuery], responses=PersonalizedDealsSerializer)
    def get(self, request):
        query = request.query_params.dict()
        if "membership_retailers" in request.query_params:
            query["membership_retailers"] = request.query_params.getlist("membership_retailers")
        form = PersonalizedDealsQuery(data=query)
        form.is_valid(raise_exception=True)
        result = personalize(request.user, product_settings(request.user), **form.validated_data)
        return Response(PersonalizedDealsSerializer(result).data)


class PersonalizedOfferReviewView(PrivateCopilotView):
    @extend_schema(request=PersonalizedReviewSerializer, responses=PersonalizedReviewSerializer)
    def put(self, request, preference_id, offer_id):
        preference = get_object_or_404(
            ProductPreference.objects.select_related("product"), owner=request.user, pk=preference_id,
        )
        form = PersonalizedReviewSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        decision = form.validated_data["decision"]
        offer = get_object_or_404(
            GroceryOffer.objects.current(now=timezone.now()), pk=offer_id, availability_status="advertised", price__gt=0,
        )
        if preference.muted or preference.excluded or not discount_met(preference, offer):
            raise ValidationError({"decision": "This offer is outside the active preference."})
        target, product = interest_product(preference), describe(offer)
        result = assess(preference, target, offer, product)
        if result is None or product.unit_price is None:
            raise ValidationError({"decision": "An incompatible offer cannot be reviewed."})
        if decision == PersonalizedOfferReview.Decision.ACCEPT and result[0] != "needs_review":
            raise ValidationError({"decision": "Only uncertain matches require acceptance."})
        PersonalizedOfferReview.objects.update_or_create(
            preference=preference, offer=offer,
            defaults={"decision": decision, "signature": input_signature(preference, target, product)},
        )
        return Response({"decision": decision})

    @extend_schema(responses={204: None})
    def delete(self, request, preference_id, offer_id):
        preference = get_object_or_404(ProductPreference, owner=request.user, pk=preference_id)
        PersonalizedOfferReview.objects.filter(preference=preference, offer_id=offer_id).delete()
        return Response(status=204)
