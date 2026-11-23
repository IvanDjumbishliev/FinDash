from django.contrib.auth import get_user_model
from django.core.exceptions import TooManyFilesSent
from django.db import transaction
from django.db.models import Exists, OuterRef, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from api.models import LoyaltyCard, LoyaltyCardImage
from api.services.loyalty import MEMBERSHIP_ID, resembles_payment_card, valid_gs1_identifier
from api.services.receipts import MAX_BYTES, ReceiptScanError, receipt_image
from api.throttles import SensitiveEndpointThrottle

from .assistant import PrivateCopilotView, PromptField, StrictBooleanField
from .receipts import BoundedReceiptUpload

MAX_CARDS = 100
MAX_IMAGES_SIZE = 32 * 1024 * 1024


def owned_cards(owner):
    return LoyaltyCard.objects.filter(owner=owner).annotate(
        has_image=Exists(LoyaltyCardImage.objects.filter(card_id=OuterRef("pk"))),
    )


class LoyaltyCardSummary(serializers.ModelSerializer):
    has_image = serializers.BooleanField(read_only=True)

    class Meta:
        model = LoyaltyCard
        fields = ("id", "retailer", "label", "code_format", "favorite", "has_image")


class LoyaltyCardDetail(LoyaltyCardSummary):
    class Meta(LoyaltyCardSummary.Meta):
        fields = (*LoyaltyCardSummary.Meta.fields, "identifier")


class LoyaltyCardWrite(serializers.ModelSerializer):
    identifier = PromptField(max_length=64, trim_whitespace=False, write_only=True)
    original_format_confirmed = StrictBooleanField(required=False, write_only=True)
    favorite = StrictBooleanField(required=False)

    class Meta:
        model = LoyaltyCard
        fields = ("retailer", "label", "identifier", "code_format", "original_format_confirmed", "favorite")

    def validate_identifier(self, value):
        if not MEMBERSHIP_ID.fullmatch(value) or resembles_payment_card(value):
            raise ValidationError("Enter only the membership identifier from the original loyalty card.")
        return value

    def validate(self, attrs):
        if set(self.initial_data) - set(self.fields):
            raise ValidationError("Only loyalty card fields are accepted.")
        previous_id = getattr(self.instance, "identifier", None)
        previous_format = getattr(self.instance, "code_format", LoyaltyCard.CodeFormat.NONE)
        identifier = attrs.get("identifier", previous_id)
        code_format = attrs.get("code_format", previous_format)
        verified = attrs.pop("original_format_confirmed", False)
        if code_format != LoyaltyCard.CodeFormat.NONE:
            if (identifier != previous_id or code_format != previous_format) and not verified:
                raise ValidationError({"code_format": "Confirm that this is the original card's format and exact encoded identifier."})
            if not valid_gs1_identifier(identifier, code_format):
                raise ValidationError({"identifier": "This identifier has an invalid length or check digit for the selected format."})
        return attrs


class LoyaltyCardListView(PrivateCopilotView):
    @extend_schema(responses=LoyaltyCardSummary(many=True))
    def get(self, request):
        return Response(LoyaltyCardSummary(owned_cards(request.user).defer("identifier"), many=True).data)

    @extend_schema(request=LoyaltyCardWrite, responses={201: LoyaltyCardSummary})
    @transaction.atomic
    def post(self, request):
        form = LoyaltyCardWrite(data=request.data)
        form.is_valid(raise_exception=True)
        get_user_model().objects.select_for_update().only("pk").get(pk=request.user.pk)
        if owned_cards(request.user).count() >= MAX_CARDS:
            raise ValidationError("Remove a card before adding another.")
        card = form.save(owner=request.user)
        card.has_image = False
        return Response(LoyaltyCardSummary(card).data, status=201)


class LoyaltyCardDetailView(PrivateCopilotView):
    @extend_schema(responses=LoyaltyCardDetail)
    def get(self, request, pk):
        return Response(LoyaltyCardDetail(get_object_or_404(owned_cards(request.user), pk=pk)).data)

    @extend_schema(request=LoyaltyCardWrite, responses=LoyaltyCardSummary)
    @transaction.atomic
    def patch(self, request, pk):
        card = get_object_or_404(owned_cards(request.user).select_for_update(), pk=pk)
        form = LoyaltyCardWrite(card, data=request.data, partial=True)
        form.is_valid(raise_exception=True)
        return Response(LoyaltyCardSummary(form.save()).data)

    @extend_schema(responses={204: None})
    def delete(self, request, pk):
        get_object_or_404(owned_cards(request.user), pk=pk).delete()
        return Response(status=204)


class LoyaltyImageUpload(serializers.Serializer):
    file = serializers.FileField()
    loyalty_only = serializers.ChoiceField(choices=["true"])


class LoyaltyCardImageView(PrivateCopilotView):
    parser_classes = [MultiPartParser]
    throttle_classes = [SensitiveEndpointThrottle]
    throttle_scope = "loyalty_image"

    @extend_schema(responses={(200, "image/png"): OpenApiTypes.BINARY})
    def get(self, request, pk):
        image = get_object_or_404(LoyaltyCardImage, card_id=pk, card__owner=request.user)
        response = HttpResponse(bytes(image.content), content_type="image/png")
        response["Content-Disposition"] = 'attachment; filename="loyalty-card.png"'
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return response

    @extend_schema(request=LoyaltyImageUpload, responses={204: None})
    def post(self, request, pk):
        get_object_or_404(owned_cards(request.user), pk=pk)
        limiter = BoundedReceiptUpload(request._request)
        request._request.upload_handlers = [limiter]
        try:
            data = request.data
        except TooManyFilesSent as error:
            raise ValidationError({"file": "Upload exactly one loyalty card image."}) from error
        if limiter.exceeded:
            return Response({"detail": "Images must be 8 MB or smaller."}, status=413)
        if len(request.FILES) != 1 or len(request.FILES.getlist("file")) != 1:
            raise ValidationError({"file": "Upload exactly one loyalty card image."})
        if data.getlist("loyalty_only") != ["true"]:
            raise ValidationError({"file": "Confirm that the image contains only a loyalty card."})
        form = LoyaltyImageUpload(data=data)
        form.is_valid(raise_exception=True)
        try:
            _, content = receipt_image(form.validated_data["file"])
        except ReceiptScanError as error:
            return Response({"detail": str(error)}, status=error.status)
        if len(content) > MAX_BYTES:
            return Response({"detail": "Use a smaller loyalty card image."}, status=413)
        with transaction.atomic():
            get_user_model().objects.select_for_update().only("pk").get(pk=request.user.pk)
            card = get_object_or_404(owned_cards(request.user).select_for_update(), pk=pk)
            used = LoyaltyCardImage.objects.filter(card__owner=request.user).exclude(card=card).aggregate(
                used=Sum("byte_size", default=0),
            )["used"]
            if used + len(content) > MAX_IMAGES_SIZE:
                raise ValidationError("Your image storage is full. Remove an image before uploading another.")
            LoyaltyCardImage.objects.update_or_create(card=card, defaults={"content": content, "byte_size": len(content)})
        return Response(status=204)

    @extend_schema(responses={204: None})
    def delete(self, request, pk):
        card = get_object_or_404(owned_cards(request.user), pk=pk)
        LoyaltyCardImage.objects.filter(card=card).delete()
        return Response(status=204)
