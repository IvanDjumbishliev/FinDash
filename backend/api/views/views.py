from django.shortcuts import render
from django.contrib.auth.models import User
from rest_framework import generics, serializers
from django.core.paginator import Paginator
from ..serializers import UserSerializer, TransactionSerializer
from rest_framework.permissions import IsAuthenticated, AllowAny
from ..models import Transaction, UserProfile
from api.services.notification_events import check_budgets, transaction_recorded
from api.services.notifications import after_commit
from api.throttles import SensitiveEndpointThrottle
from rest_framework.generics import ListCreateAPIView, DestroyAPIView
from django.db.models import Sum
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import filters
from decimal import Decimal
from rest_framework_simplejwt.tokens import RefreshToken


class GetProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # converts username from json to string
        user = str(request.user)
        return Response(user, status=200)


class CreateUserView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [SensitiveEndpointThrottle]
    throttle_scope = "registration"

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "id": user.id,
                "username": user.username,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
            status=201,
        )


class TransactionListView(ListCreateAPIView):
    queryset = Transaction.objects.all()
    serializer_class = TransactionSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["timestamp", "id"]

    def get_queryset(self):
        user = self.request.user
        return Transaction.objects.filter(user=user)

    def perform_create(self, serializer):
        item = serializer.save(user=self.request.user)
        after_commit(transaction_recorded, item.user_id, item.pk)


class TransactionStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        # only get expenses
        expenses = (
            Transaction.objects.filter(
                user=user, amount__lt=0  # less than 0 to get only expenses
            )
            .values("category")
            .annotate(total_amount=Sum("amount"))  # Sum amounts for each category
            .values("category", "total_amount")
        )

        stats = [
            {
                "category": expense["category"],
                "amount": abs(
                    float(expense["total_amount"])
                ),  # Convert to positive number for frontend
            }
            for expense in expenses
        ]

        return Response(stats, status=200)


class TransactionDeleteView(DestroyAPIView):
    queryset = Transaction.objects.all()
    serializer_class = TransactionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Transaction.objects.filter(user=self.request.user)

    def perform_destroy(self, instance):
        period = timezone.localtime(instance.timestamp).date().replace(day=1)
        owner_id = instance.user_id
        super().perform_destroy(instance)
        after_commit(check_budgets, owner_id, {period})
