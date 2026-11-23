from functools import wraps

from django.contrib.auth import get_user_model
from django.db import DatabaseError, OperationalError, connection, transaction
from django.db.models import Prefetch, prefetch_related_objects
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import serializers
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response

from api.models import GroceryListItem, GroceryListMember
from api.services.grocery_basket import BasketLimit, optimize_basket
from api.services.shared_grocery import visible_lists, writable_list
from api.throttles import SensitiveEndpointThrottle

from .assistant import PrivateCopilotView, StrictBooleanField
from .grocery import GroceryBasketInput, ShoppingListItem, ShoppingListOutput, saved_product


class EditConflict(APIException):
    status_code = 409
    default_detail = "This item changed. Reload before editing it again."


def household_write(method):
    @wraps(method)
    def run(*args, **kwargs):
        try:
            with transaction.atomic():
                return method(*args, **kwargs)
        except OperationalError as error:
            if connection.vendor == "sqlite" and "locked" in str(error).lower():
                raise EditConflict("Another edit is in progress. Reload and try again.") from error
            raise
    return run


class SharedItemOutput(serializers.ModelSerializer):
    added_by = serializers.CharField(source="added_by.username", allow_null=True)
    completed_by = serializers.CharField(source="completed_by.username", allow_null=True)

    class Meta:
        model = GroceryListItem
        fields = ("id", "product", "added_by", "completed_by", "purchased", "revision")


class MembershipOutput(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username")

    class Meta:
        model = GroceryListMember
        fields = ("id", "username", "accepted")


class HouseholdOutput(ShoppingListOutput):
    items = SharedItemOutput(source="shared_items", many=True, read_only=True)
    members = serializers.SerializerMethodField()

    class Meta(ShoppingListOutput.Meta):
        fields = (*ShoppingListOutput.Meta.fields, "items", "members")

    @extend_schema_field(MembershipOutput(many=True))
    def get_members(self, record):
        if record.owner_id != self.context["request"].user.pk:
            return []
        return MembershipOutput(record.memberships.select_related("user").order_by("pk"), many=True).data


class InviteInput(serializers.Serializer):
    username = serializers.CharField(max_length=150)


class InvitationOutput(serializers.ModelSerializer):
    list_id = serializers.IntegerField(source="shopping_list_id")
    name = serializers.CharField(source="shopping_list.name")
    invited_by = serializers.CharField(source="shopping_list.owner.username")

    class Meta:
        model = GroceryListMember
        fields = ("list_id", "name", "invited_by")


class InvitationDecision(serializers.Serializer):
    accept = StrictBooleanField()


class ItemVersion(serializers.Serializer):
    revision = serializers.IntegerField(min_value=0, max_value=2**31 - 1)


class ItemChange(ItemVersion):
    quantity = serializers.CharField(max_length=24, required=False)
    purchased = StrictBooleanField(required=False)

    def validate(self, data):
        if not ({"quantity", "purchased"} & data.keys()):
            raise ValidationError("Supply a quantity or purchased status.")
        return data


def shared_record(request, pk):
    return get_object_or_404(visible_lists(request.user).filter(shared=True), pk=pk)


class HouseholdView(PrivateCopilotView):
    @extend_schema(responses=HouseholdOutput)
    def get(self, request, pk):
        record = shared_record(request, pk)
        prefetch_related_objects([record], Prefetch(
            "shared_items", queryset=GroceryListItem.objects.select_related("added_by", "completed_by"),
        ))
        data = HouseholdOutput(record, context={"request": request}).data
        shared_record(request, pk)
        return Response(data)

    @extend_schema(request=None, responses={204: None})
    @household_write
    def post(self, request, pk):
        record = writable_list(request.user, pk, owner_only=True, require_shared=False)
        if not record.shared:
            GroceryListItem.objects.bulk_create([GroceryListItem(
                shopping_list=record, product=product, added_by=request.user,
            ) for product in record.settings.get("items", [])])
            record.shared = True
            record.settings = {**record.settings, "items": []}
            record.save(update_fields=["shared", "settings"])
        return Response(status=204)


class HouseholdMemberView(PrivateCopilotView):
    throttle_classes = [SensitiveEndpointThrottle]
    throttle_scope = "grocery_invite"

    @extend_schema(request=InviteInput, responses={201: MembershipOutput})
    @household_write
    def post(self, request, pk):
        record = writable_list(request.user, pk, owner_only=True)
        form = InviteInput(data=request.data)
        form.is_valid(raise_exception=True)
        invited = get_user_model().objects.filter(username=form.validated_data["username"], is_active=True).first()
        if invited is None or invited == request.user:
            raise ValidationError({"username": "Choose another registered FinDash user."})
        existing = record.memberships.filter(user=invited).first()
        if existing is None and record.memberships.count() >= 20:
            raise ValidationError("This list already has 20 members or pending invitations.")
        membership = existing or record.memberships.create(user=invited)
        return Response(MembershipOutput(membership).data, status=200 if existing else 201)


class HouseholdMemberDetailView(PrivateCopilotView):
    @extend_schema(responses={204: None})
    @household_write
    def delete(self, request, pk, member_id):
        record = writable_list(request.user, pk, owner_only=True)
        get_object_or_404(record.memberships, pk=member_id).delete()
        return Response(status=204)


class HouseholdInvitationsView(PrivateCopilotView):
    @extend_schema(responses=InvitationOutput(many=True))
    def get(self, request):
        rows = GroceryListMember.objects.filter(user=request.user, accepted=False, shopping_list__shared=True)
        return Response(InvitationOutput(rows.select_related("shopping_list__owner").order_by("-pk")[:100], many=True).data)


class HouseholdInvitationView(PrivateCopilotView):
    @extend_schema(request=InvitationDecision, responses={204: None})
    @household_write
    def post(self, request, pk):
        record = writable_list(request.user, pk, invited=True)
        form = InvitationDecision(data=request.data)
        form.is_valid(raise_exception=True)
        membership = get_object_or_404(record.memberships, user=request.user, accepted=False)
        if form.validated_data["accept"]:
            membership.accepted = True
            membership.save(update_fields=["accepted"])
        else:
            membership.delete()
        return Response(status=204)


def validate_open_products(record, product, *, except_item=None):
    rows = record.shared_items.filter(purchased=False).exclude(pk=except_item).values_list("product", flat=True)
    form = GroceryBasketInput(data={**record.settings, "items": [*rows, product]})
    form.is_valid(raise_exception=True)


class HouseholdItemsView(PrivateCopilotView):
    @extend_schema(request=ShoppingListItem, responses={201: SharedItemOutput})
    @household_write
    def post(self, request, pk):
        record = writable_list(request.user, pk)
        form = ShoppingListItem(data=request.data)
        form.is_valid(raise_exception=True)
        if record.shared_items.count() >= 40:
            raise ValidationError("This list already has 40 items.")
        data = saved_product(form.validated_data)
        validate_open_products(record, data)
        item = record.shared_items.create(product=data, added_by=request.user)
        return Response(SharedItemOutput(item).data, status=201)


class HouseholdItemDetailView(PrivateCopilotView):
    def versioned_item(self, request, pk, item_id, version):
        record = writable_list(request.user, pk)
        item = get_object_or_404(record.shared_items.select_related("added_by", "completed_by"), pk=item_id)
        if item.revision != version:
            raise EditConflict()
        return record, item

    @extend_schema(request=ItemChange, responses=SharedItemOutput)
    @household_write
    def patch(self, request, pk, item_id):
        form = ItemChange(data=request.data)
        form.is_valid(raise_exception=True)
        data = form.validated_data
        record, item = self.versioned_item(request, pk, item_id, data["revision"])
        if "quantity" in data:
            product = ShoppingListItem(data={**item.product, "quantity": data["quantity"]})
            product.is_valid(raise_exception=True)
            item.product = saved_product(product.validated_data)
        if "purchased" in data and data["purchased"] != item.purchased:
            item.purchased = data["purchased"]
            item.completed_by = request.user if item.purchased else None
        if not item.purchased:
            validate_open_products(record, item.product, except_item=item.pk)
        item.revision += 1
        item.save(update_fields=["product", "purchased", "completed_by", "revision"])
        return Response(SharedItemOutput(item).data)

    @extend_schema(parameters=[ItemVersion], responses={204: None})
    @household_write
    def delete(self, request, pk, item_id):
        form = ItemVersion(data=request.query_params)
        form.is_valid(raise_exception=True)
        _, item = self.versioned_item(request, pk, item_id, form.validated_data["revision"])
        item.delete()
        return Response(status=204)


class HouseholdOptimizeView(PrivateCopilotView):
    throttle_classes = [SensitiveEndpointThrottle]
    throttle_scope = "grocery_optimize"

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    def post(self, request, pk):
        record = shared_record(request, pk)
        rows = list(record.shared_items.filter(purchased=False).values_list("product", flat=True))
        form = GroceryBasketInput(data={**record.settings, "items": rows})
        form.is_valid(raise_exception=True)
        try:
            result = optimize_basket(**form.validated_data)
        except BasketLimit as error:
            response = Response({"error": str(error)}, status=422)
        except DatabaseError:
            response = Response({"error": "The grocery catalog is temporarily unavailable."}, status=503)
        else:
            response = Response(result)
        shared_record(request, pk)
        return response
