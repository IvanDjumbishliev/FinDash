from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response

from api.models import Budget, BudgetSuggestionReview, Transaction
from api.services.budget_explanations import explain_recommendations
from api.services.budget_recommendations import generate_recommendations
from api.services.budgets import parse_month
from api.services.notification_events import check_budgets
from api.services.notifications import after_commit

from .budgets import BudgetView

REVIEW_TIMEOUT = timedelta(minutes=30)


class ExplicitBooleanField(serializers.BooleanField):
    def to_internal_value(self, data):
        if type(data) is not bool:
            self.fail("invalid", input=data)
        return data


class RecommendationRequest(serializers.Serializer):
    period = serializers.CharField()
    use_gemini = ExplicitBooleanField(default=False)

    def validate_period(self, value):
        try:
            return parse_month(value)
        except ValueError as error:
            raise serializers.ValidationError(str(error)) from error


class ApprovalRequest(serializers.Serializer):
    review_id = serializers.UUIDField()
    categories = serializers.ListField(
        child=serializers.ChoiceField(choices=Transaction.Category.choices),
        allow_empty=False, max_length=len(Transaction.Category.values),
    )
    confirmed = ExplicitBooleanField()

    def validate_confirmed(self, value):
        if not value:
            raise serializers.ValidationError("Confirm the selection before applying it.")
        return value

    def validate_categories(self, values):
        if len(set(values)) != len(values):
            raise serializers.ValidationError("Select each category once.")
        return values


class BudgetRecommendationView(BudgetView):
    serializer_class = RecommendationRequest

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        period = data["period"]
        current_month = timezone.localdate().replace(day=1)
        suggestions, existing = generate_recommendations(request.user, period, current_month)
        ai_status = explain_recommendations(suggestions, consent=data["use_gemini"])
        review = None
        now = timezone.now()
        BudgetSuggestionReview.objects.filter(owner=request.user, expires_at__lte=now).delete()
        if suggestions:
            selections = {}
            for item in suggestions:
                category = item["category"]
                budget = existing.get(category)
                selections[category] = {
                    "amount": item["suggested_amount"], "currency": item["currency"],
                    "budget_id": budget.pk if budget else None,
                    "updated_at": budget.updated_at.isoformat() if budget else None,
                }
            review = BudgetSuggestionReview.objects.create(
                owner=request.user, period=period, selections=selections,
                expires_at=now + REVIEW_TIMEOUT,
            )
        return Response({
            "period": period.isoformat(),
            "review_id": str(review.pk) if review else None,
            "expires_at": review.expires_at.isoformat() if review else None,
            "status": "ready" if review else "insufficient_history",
            "ai_status": ai_status,
            "recommendations": suggestions,
        })


class StaleReview(Exception):
    pass


class BudgetRecommendationApplyView(BudgetView):
    serializer_class = ApprovalRequest

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        approved = serializer.validated_data
        try:
            with transaction.atomic():
                review = BudgetSuggestionReview.objects.select_for_update().filter(
                    pk=approved["review_id"], owner=request.user,
                    expires_at__gt=timezone.now(),
                ).first()
                if review is None:
                    return Response(
                        {"detail": "This review is unavailable or expired. Generate new suggestions."},
                        status=status.HTTP_404_NOT_FOUND,
                    )
                if not set(approved["categories"]).issubset(review.selections):
                    raise serializers.ValidationError({"categories": "Select categories from this review."})
                applied = []
                for category in sorted(approved["categories"]):
                    item = review.selections[category]
                    budgets = Budget.objects.filter(
                        owner=request.user, period=review.period, category=category, archived=False,
                    )
                    if item["budget_id"] is None:
                        if budgets.exists():
                            raise StaleReview
                        budget = Budget.objects.create(
                            owner=request.user, period=review.period, category=category,
                            amount=item["amount"], currency=item["currency"],
                        )
                        budget_id = budget.pk
                    else:
                        budget_id = item["budget_id"]
                        changed = budgets.filter(
                            pk=budget_id, updated_at=item["updated_at"], currency=item["currency"],
                        ).update(amount=item["amount"], updated_at=timezone.now())
                        if not changed:
                            raise StaleReview
                    applied.append({"id": budget_id, "category": category})
                review.delete()
                after_commit(check_budgets, request.user.pk, {review.period})
        except (StaleReview, IntegrityError):
            return Response(
                {"detail": "A budget changed after this review. Generate new suggestions before applying."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response({"period": review.period.isoformat(), "applied": applied})
