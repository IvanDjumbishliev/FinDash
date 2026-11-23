from django.contrib.auth import get_user_model
from django.core.exceptions import TooManyFilesSent
from django.db import transaction
from django.db.models import Exists, OuterRef, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from api.models import Receipt, ReceiptItem, Warranty, WarrantyProof
from api.services.grocery_catalog import normalized
from api.services.receipts import MAX_BYTES, SOFIA, ReceiptScanError, receipt_image
from api.services.warranties import MAX_PROOF_STORAGE, MAX_RECORDS, delete_warranties, expiry_from_months, warranty_today
from api.throttles import SensitiveEndpointThrottle

from .assistant import PrivateCopilotView
from .receipts import BoundedReceiptUpload

PURCHASE_FIELDS = ("product_name", "retailer", "purchased_on")


class WarrantySerializer(serializers.ModelSerializer):
    has_proof = serializers.BooleanField(read_only=True)
    status = serializers.SerializerMethodField()
    receipt_id = serializers.UUIDField(source="receipt_item.receipt_id", read_only=True, allow_null=True)

    class Meta:
        model = Warranty
        fields = ("id", "receipt_item", "receipt_id", *PURCHASE_FIELDS, "duration_months", "expires_on",
                  "field_sources", "status", "reminder_days", "has_proof", "created_at", "updated_at")
        read_only_fields = fields

    def get_status(self, warranty) -> str:
        today = self.context["today"]
        return "expired" if warranty.expires_on < today else "active"


class WarrantyWriteSerializer(serializers.ModelSerializer):
    receipt_item = serializers.IntegerField(source="receipt_item_id", min_value=1, max_value=2**63 - 1,
                                            required=False, allow_null=True)
    duration_months = serializers.IntegerField(min_value=1, max_value=600, required=False, allow_null=True)
    reminder_days = serializers.ListField(child=serializers.IntegerField(min_value=0, max_value=365),
                                          max_length=4, required=False)
    product_name = serializers.CharField(required=False, max_length=255)
    retailer = serializers.CharField(required=False, max_length=255)
    purchased_on = serializers.DateField(required=False)
    expires_on = serializers.DateField(required=False)

    class Meta:
        model = Warranty
        fields = ("receipt_item", *PURCHASE_FIELDS, "duration_months", "expires_on", "reminder_days")

    def validate(self, attrs):
        owner = self.context["owner"]
        instance = self.instance
        sources = dict(instance.field_sources) if instance else {}
        linked = None
        if attrs.get("receipt_item_id") is not None:
            linked = get_object_or_404(
                ReceiptItem.objects.select_related("receipt"),
                pk=attrs["receipt_item_id"], receipt__owner=owner, receipt__status=Receipt.Status.CONFIRMED,
            )
        extracted = {}
        if linked:
            extracted = {
                "product_name": linked.original_description.strip(), "retailer": linked.receipt.merchant.strip(),
                "purchased_on": linked.receipt.purchased_at.astimezone(SOFIA).date(),
            }
        relink = linked is not None and (not instance or linked.pk != instance.receipt_item_id)
        for field in PURCHASE_FIELDS:
            existing = getattr(instance, field, None)
            if field in attrs:
                if relink or not instance or existing != attrs[field]:
                    sources[field] = "manual"
            elif relink and extracted.get(field):
                attrs[field] = extracted[field]
                sources[field] = "receipt"
            elif not existing:
                raise ValidationError({field: "Provide this purchase detail or choose a confirmed receipt item."})
        purchase = attrs.get("purchased_on") or instance.purchased_on
        if purchase > self.context["today"] and sources.get("purchased_on") != "receipt":
            raise ValidationError({"purchased_on": "The purchase date cannot be in the future."})
        months = attrs.get("duration_months", getattr(instance, "duration_months", None))
        explicit_expiry = attrs.get("expires_on")
        if months is not None:
            try:
                end = expiry_from_months(purchase, months)
            except ValueError as error:
                raise ValidationError({"duration_months": "The resulting date is out of range."}) from error
            if explicit_expiry and explicit_expiry != end:
                raise ValidationError({"expires_on": "Use the date calculated from the duration, or clear duration to set an explicit date."})
            sources["expires_on"] = "calculated"
            sources["duration_months"] = "manual"
        else:
            if instance and instance.duration_months is not None and not explicit_expiry:
                raise ValidationError({"expires_on": "Enter the documented expiration date when clearing duration."})
            end = explicit_expiry or getattr(instance, "expires_on", None)
            if end is None:
                raise ValidationError({"expires_on": "Enter a documented expiration date or warranty duration."})
            sources.pop("duration_months", None)
            sources["expires_on"] = "manual"
        if end < purchase:
            raise ValidationError({"expires_on": "Expiration must be on or after the purchase date."})
        search_text = "\n".join(normalized(attrs.get(field, getattr(instance, field, ""))) for field in ("product_name", "retailer"))
        attrs.update(expires_on=end, field_sources=sources, search_text=search_text)
        if "reminder_days" in attrs:
            attrs["reminder_days"] = sorted(set(attrs["reminder_days"]))
        return attrs


class WarrantyFilters(serializers.Serializer):
    q = serializers.CharField(required=False, allow_blank=True, max_length=120)
    status = serializers.ChoiceField(choices=["active", "expired"], required=False)


class WarrantyPagination(PageNumberPagination):
    page_size = 20


def warranty_rows(owner):
    return (Warranty.objects.filter(owner=owner).select_related("receipt_item")
            .annotate(has_proof=Exists(WarrantyProof.objects.filter(warranty_id=OuterRef("pk")))))


class WarrantyContext:
    def get_serializer_context(self):
        return {**super().get_serializer_context(), "today": warranty_today(self.request.user)}


class WarrantyListView(WarrantyContext, PrivateCopilotView, generics.ListAPIView):
    serializer_class = WarrantySerializer
    pagination_class = WarrantyPagination
    queryset = Warranty.objects.none()

    def get_queryset(self):
        form = WarrantyFilters(data=self.request.query_params)
        form.is_valid(raise_exception=True)
        params = form.validated_data
        rows = warranty_rows(self.request.user)
        if term := params.get("q"):
            identity = normalized(term)
            raw = Q(product_name__icontains=term) | Q(retailer__icontains=term)
            rows = rows.filter(raw | Q(search_text__contains=identity)) if identity else rows.filter(raw)
        if state := params.get("status"):
            today = warranty_today(self.request.user)
            rows = rows.filter(expires_on__lt=today) if state == "expired" else rows.filter(expires_on__gte=today)
        return rows

    @extend_schema(parameters=[WarrantyFilters])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(request=WarrantyWriteSerializer, responses={201: WarrantySerializer})
    @transaction.atomic
    def post(self, request):
        get_user_model().objects.select_for_update().only("pk").get(pk=request.user.pk)
        if Warranty.objects.filter(owner=request.user).count() >= MAX_RECORDS:
            raise ValidationError("Remove a warranty before adding another.")
        form = WarrantyWriteSerializer(data=request.data, context={"owner": request.user, **self.get_serializer_context()})
        form.is_valid(raise_exception=True)
        warranty = form.save(owner=request.user)
        return Response(self.get_serializer(warranty_rows(request.user).get(pk=warranty.pk)).data, status=201)


class WarrantyDetailView(WarrantyContext, PrivateCopilotView, generics.RetrieveDestroyAPIView):
    serializer_class = WarrantySerializer
    queryset = Warranty.objects.none()

    def get_queryset(self):
        return warranty_rows(self.request.user)

    @transaction.atomic
    def delete(self, request, pk):
        rows = Warranty.objects.filter(owner=request.user, pk=pk)
        if not delete_warranties(rows):
            get_object_or_404(rows)
        return Response(status=204)

    @extend_schema(request=WarrantyWriteSerializer, responses=WarrantySerializer)
    @transaction.atomic
    def patch(self, request, pk):
        warranty = get_object_or_404(Warranty.objects.select_for_update(), owner=request.user, pk=pk)
        form = WarrantyWriteSerializer(warranty, data=request.data, partial=True,
                                       context={"owner": request.user, **self.get_serializer_context()})
        form.is_valid(raise_exception=True)
        form.save()
        return Response(self.get_serializer(warranty_rows(request.user).get(pk=pk)).data)


class WarrantyProofUpload(serializers.Serializer):
    file = serializers.FileField()


class WarrantyProofView(PrivateCopilotView):
    parser_classes = [MultiPartParser]
    throttle_classes = [SensitiveEndpointThrottle]
    throttle_scope = "warranty_proof"

    @extend_schema(responses={(200, "image/png"): OpenApiTypes.BINARY})
    def get(self, request, pk):
        proof = get_object_or_404(WarrantyProof, warranty_id=pk, warranty__owner=request.user)
        response = HttpResponse(bytes(proof.image), content_type="image/png")
        response["Content-Disposition"] = 'attachment; filename="purchase-proof.png"'
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return response

    @extend_schema(request=WarrantyProofUpload, responses={204: None})
    def post(self, request, pk):
        get_object_or_404(Warranty, owner=request.user, pk=pk)
        handler = BoundedReceiptUpload(request._request)
        request._request.upload_handlers = [handler]
        try:
            payload = request.data
        except TooManyFilesSent as error:
            raise ValidationError({"file": "Upload one proof image."}) from error
        if handler.exceeded:
            return Response({"detail": "Proof images must be 8 MB or smaller."}, status=413)
        if len(request.FILES) != 1 or len(request.FILES.getlist("file")) != 1:
            raise ValidationError({"file": "Upload one proof image."})
        form = WarrantyProofUpload(data=payload)
        form.is_valid(raise_exception=True)
        try:
            _, image = receipt_image(form.validated_data["file"])
        except ReceiptScanError as error:
            return Response({"detail": str(error)}, status=error.status)
        if len(image) > MAX_BYTES:
            return Response({"detail": "Use a smaller proof image."}, status=413)
        with transaction.atomic():
            get_user_model().objects.select_for_update().only("pk").get(pk=request.user.pk)
            warranty = get_object_or_404(Warranty.objects.select_for_update(), owner=request.user, pk=pk)
            total = WarrantyProof.objects.filter(warranty__owner=request.user).exclude(warranty=warranty).aggregate(
                total=Sum("byte_size", default=0),
            )["total"]
            if total + len(image) > MAX_PROOF_STORAGE:
                raise ValidationError("Your proof storage is full. Remove an attachment before uploading another.")
            WarrantyProof.objects.update_or_create(warranty=warranty, defaults={"image": image, "byte_size": len(image)})
        return Response(status=204)

    @extend_schema(responses={204: None})
    def delete(self, request, pk):
        warranty = get_object_or_404(Warranty, owner=request.user, pk=pk)
        WarrantyProof.objects.filter(warranty=warranty).delete()
        return Response(status=204)
