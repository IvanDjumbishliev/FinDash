from django.db import IntegrityError, transaction
from rest_framework import generics, serializers
from rest_framework.permissions import IsAuthenticated

from api.models import MerchantCategoryRule, Transaction
from api.services.statements.intelligence import merchant_identity
from api.services.statements.normalization import MAX_ROWS


class ReviewChangeSerializer(serializers.Serializer):
    row_id = serializers.IntegerField(min_value=1)
    merchant = serializers.CharField(max_length=255, required=False)
    category = serializers.ChoiceField(choices=Transaction.Category.choices, required=False)
    decision = serializers.ChoiceField(choices=["approved", "rejected", "pending"], required=False)
    allow_duplicate = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        if not {"merchant", "category", "decision"} & attrs.keys():
            raise serializers.ValidationError("Specify a correction or decision for each selected row.")
        return attrs


class ReviewRequestSerializer(serializers.Serializer):
    revision = serializers.IntegerField(min_value=0)
    changes = ReviewChangeSerializer(many=True, allow_empty=False, max_length=MAX_ROWS)

    def validate_changes(self, changes):
        if len({row["row_id"] for row in changes}) != len(changes):
            raise serializers.ValidationError("Each row can appear only once.")
        return changes


class ConfirmationSerializer(serializers.Serializer):
    revision = serializers.IntegerField(min_value=0, required=False)


class MerchantRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = MerchantCategoryRule
        fields = ["id", "merchant", "category"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        merchant = attrs.get("merchant", self.instance.merchant if self.instance else "")
        display, identity = merchant_identity(merchant)
        if not identity:
            raise serializers.ValidationError({"merchant": "Enter a merchant name with at least one letter."})
        attrs.update(merchant=display, normalized_merchant=identity)
        return attrs


class MerchantRuleView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MerchantRuleSerializer

    def get_queryset(self):
        return MerchantCategoryRule.objects.filter(owner=self.request.user)

    def save_rule(self, serializer):
        try:
            with transaction.atomic():
                serializer.save(owner=self.request.user)
        except IntegrityError as error:
            raise serializers.ValidationError({"merchant": "A rule already exists for this merchant."}) from error


class MerchantRuleListView(generics.ListCreateAPIView, MerchantRuleView):
    def perform_create(self, serializer):
        self.save_rule(serializer)


class MerchantRuleDetailView(generics.RetrieveUpdateDestroyAPIView, MerchantRuleView):
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def perform_update(self, serializer):
        self.save_rule(serializer)
