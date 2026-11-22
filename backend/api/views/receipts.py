from decimal import Decimal

from django.core import signing
from django.core.files.uploadhandler import MemoryFileUploadHandler, StopUpload
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import generics, serializers
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from api.models import GroceryOffer, Receipt, ReceiptItem, Transaction
from api.services.grocery_catalog import normalized
from api.services.grocery_matching import classify
from api.services.receipts import (
    MAX_BYTES, MAX_ITEMS, ReceiptScanError, extract_receipt, receipt_fingerprint, receipt_image, recognize_receipt,
)
from api.throttles import SensitiveEndpointThrottle

from .assistant import PrivateCopilotView

PREVIEW_SALT = "findash.receipt.preview.v1"
PREVIEW_MAX_AGE = 3600


class BoundedReceiptUpload(MemoryFileUploadHandler):
    """Keep the small image in memory and place a limit on streamed bytes."""

    received = 0
    exceeded = False

    def handle_raw_input(self, input_data, META, content_length, boundary, encoding=None):
        self.activated = True

    def receive_data_chunk(self, raw_data, start):
        self.received += len(raw_data)
        if self.received > MAX_BYTES:
            self.exceeded = True
            raise StopUpload()
        return super().receive_data_chunk(raw_data, start)


class ReceiptPreviewUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    source = serializers.ChoiceField(choices=Receipt.Source.choices, default=Receipt.Source.UPLOAD)
    date_order = serializers.ChoiceField(choices=["DMY", "MDY"], default="DMY")


class ReceiptPreviewSerializer(serializers.Serializer):
    token = serializers.CharField(allow_null=True)
    receipt = serializers.DictField(allow_null=True)
    duplicate_id = serializers.UUIDField(allow_null=True)
    status = serializers.ChoiceField(choices=["review_required", "duplicate"])


class ReviewedReceiptItemSerializer(serializers.ModelSerializer):
    # Resolve selected public catalog IDs in one query at confirmation.
    product = serializers.IntegerField(source="product_id", min_value=1, max_value=2**63 - 1, required=False, allow_null=True)
    confidence = serializers.DecimalField(
        max_digits=3, decimal_places=2, min_value=Decimal("0"), max_value=Decimal("1"),
        required=False, allow_null=True,
    )

    class Meta:
        model = ReceiptItem
        read_only_fields = ["normalized_name"]
        fields = (
            "original_description", "normalized_name", "quantity", "unit", "unit_price", "line_total",
            "discount", "category", "brand", "confidence", "product",
        )

    def validate_original_description(self, value):
        if not normalized(value) or not value.isprintable():
            raise ValidationError("Enter a valid item description.")
        return value

    def validate(self, attrs):
        if attrs.get("quantity") == 0:
            raise ValidationError({"quantity": "Quantity cannot be zero."})
        if attrs.get("quantity") is None and attrs.get("unit"):
            raise ValidationError({"unit": "A measurement unit requires a quantity."})
        return attrs


class ReceiptSerializer(serializers.ModelSerializer):
    items = ReviewedReceiptItemSerializer(many=True, read_only=True)
    reconciliation_valid = serializers.SerializerMethodField()
    transaction = serializers.SerializerMethodField()

    class Meta:
        model = Receipt
        fields = (
            "id", "merchant", "normalized_merchant", "purchased_at", "currency", "subtotal", "discounts",
            "tax_total", "total", "reference", "status", "source", "transaction", "reconciliation_valid",
            "created_at", "updated_at", "items",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_transaction(self, receipt):
        payment = receipt.transaction
        return payment.pk if payment and payment.user_id == receipt.owner_id else None

    @extend_schema_field(bool)
    def get_reconciliation_valid(self, receipt):
        payment = receipt.transaction
        return bool(payment and payment.user_id == receipt.owner_id
                    and payment.amount == -receipt.total and payment.currency.strip().upper() == receipt.currency)


class ReceiptConfirmationSerializer(serializers.ModelSerializer):
    token = serializers.CharField(max_length=512, write_only=True)
    items = ReviewedReceiptItemSerializer(many=True, allow_empty=False, max_length=MAX_ITEMS)

    class Meta:
        model = Receipt
        fields = ("token", "merchant", "purchased_at", "currency", "subtotal", "discounts", "tax_total",
                  "total", "reference", "items")
        validators = []

    def validate_merchant(self, value):
        if not normalized(value) or not value.isprintable():
            raise ValidationError("Enter a valid merchant name.")
        return value


class ReceiptReconciliationSerializer(serializers.Serializer):
    transaction = serializers.IntegerField(min_value=1, max_value=2**63 - 1, allow_null=True)


class ReceiptConflict(APIException):
    status_code = 409
    default_detail = "This payment is already linked to another receipt."


def receipt_queryset(user):
    return Receipt.objects.filter(owner=user).select_related("transaction").prefetch_related("items")


def receipt_response(request, pk, *, status=200):
    return Response(ReceiptSerializer(receipt_queryset(request.user).get(pk=pk)).data, status=status)


class ReceiptPrivateView(PrivateCopilotView):
    throttle_classes = [SensitiveEndpointThrottle]
    throttle_scope = "receipt_scan"


class ReceiptPreviewView(ReceiptPrivateView):
    parser_classes = [MultiPartParser]

    @extend_schema(request=ReceiptPreviewUploadSerializer, responses=ReceiptPreviewSerializer)
    def post(self, request):
        handler = BoundedReceiptUpload(request._request)
        request._request.upload_handlers = [handler]
        payload = request.data
        if handler.exceeded:
            return Response({"detail": "Receipt images must be 8 MB or smaller."}, status=413)
        if len(request.FILES.getlist("file")) != 1 or len(request.FILES) != 1:
            raise ValidationError({"file": "Upload exactly one receipt image."})
        upload = ReceiptPreviewUploadSerializer(data=payload)
        upload.is_valid(raise_exception=True)
        source = upload.validated_data
        try:
            digest, image = receipt_image(source["file"])
            owner_receipts = Receipt.objects.filter(owner=request.user)
            duplicate = owner_receipts.filter(image_digest=digest).values_list("pk", flat=True).first()
            scanned = None if duplicate else extract_receipt(recognize_receipt(image), source["date_order"])
        except ReceiptScanError as error:
            return Response({"detail": str(error)}, status=error.status)
        token = None if duplicate else signing.dumps(
            {"owner": request.user.pk, "digest": digest, "source": source["source"]}, salt=PREVIEW_SALT,
        )
        return Response({
            "token": token, "receipt": scanned, "duplicate_id": duplicate,
            "status": "duplicate" if duplicate else "review_required",
        })


class ReceiptConfirmationView(ReceiptPrivateView):
    @extend_schema(request=ReceiptConfirmationSerializer, responses={200: ReceiptSerializer, 201: ReceiptSerializer})
    def post(self, request):
        form = ReceiptConfirmationSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        details = dict(form.validated_data)
        try:
            preview = signing.loads(details.pop("token"), salt=PREVIEW_SALT, max_age=PREVIEW_MAX_AGE)
        except signing.BadSignature as error:
            raise ValidationError({"token": "This preview is invalid or has expired. Scan the receipt again."}) from error
        if preview["owner"] != request.user.pk:
            raise ValidationError({"token": "This preview is invalid or has expired. Scan the receipt again."})

        items = details.pop("items")
        merchant, fingerprint = receipt_fingerprint(details, items)
        owner_receipts = Receipt.objects.filter(owner=request.user)
        duplicate = Q(image_digest=preview["digest"]) | Q(fingerprint=fingerprint)
        if existing := owner_receipts.filter(duplicate).first():
            return receipt_response(request, existing.pk)
        products = GroceryOffer.objects.in_bulk({item["product_id"] for item in items if item.get("product_id")})
        rows = []
        for item in items:
            product_id = item.pop("product_id", None)
            product = products.get(product_id)
            if product_id and product is None:
                raise ValidationError({"items": "A selected catalog product no longer exists."})
            name = normalized(item["original_description"])[:255]
            suggested_category, _, _ = classify(name, "")
            item["category"] = item.get("category") or (product.category if product else "") or suggested_category
            item["brand"] = item.get("brand") or (product.brand if product else "")
            rows.append(ReceiptItem(**item, normalized_name=name, product=product))
        try:
            with transaction.atomic():
                new_receipt = owner_receipts.create(
                    **details, owner=request.user, normalized_merchant=merchant, image_digest=preview["digest"],
                    fingerprint=fingerprint, source=preview["source"],
                )
                for row in rows:
                    row.receipt = new_receipt
                ReceiptItem.objects.bulk_create(rows)
        except IntegrityError:
            existing = owner_receipts.filter(duplicate).first()
            if existing is None:
                raise
            return receipt_response(request, existing.pk)
        return receipt_response(request, new_receipt.pk, status=201)


class ReceiptPagination(PageNumberPagination):
    page_size = 20


class ReceiptListView(PrivateCopilotView, generics.ListAPIView):
    serializer_class = ReceiptSerializer
    pagination_class = ReceiptPagination
    queryset = Receipt.objects.none()

    def get_queryset(self):
        return receipt_queryset(self.request.user)


class ReceiptDetailView(PrivateCopilotView, generics.RetrieveDestroyAPIView):
    serializer_class = ReceiptSerializer
    queryset = Receipt.objects.none()

    def get_queryset(self):
        return receipt_queryset(self.request.user)


class ReceiptReconciliationView(PrivateCopilotView):
    @extend_schema(request=ReceiptReconciliationSerializer, responses=ReceiptSerializer)
    def patch(self, request, pk):
        form = ReceiptReconciliationSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        payment_id = form.validated_data["transaction"]
        try:
            with transaction.atomic():
                receipt = get_object_or_404(Receipt.objects.select_for_update(), owner=request.user, pk=pk)
                if payment_id is not None:
                    payment = get_object_or_404(Transaction.objects.select_for_update(), user=request.user, pk=payment_id)
                    if payment.amount != -receipt.total or payment.currency.strip().upper() != receipt.currency:
                        raise ValidationError({"transaction": "Choose a payment with the same currency and matching signed amount."})
                    if Receipt.objects.filter(transaction=payment).exclude(pk=pk).exists():
                        raise ReceiptConflict()
                receipt.transaction_id = payment_id
                receipt.save(update_fields=["transaction", "updated_at"])
        except IntegrityError as error:
            raise ReceiptConflict() from error
        return receipt_response(request, pk)
