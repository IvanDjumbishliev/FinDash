from django.utils import timezone
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from api.models import Subscription, SubscriptionPreferences
from api.serializers import SubscriptionPreferencesSerializer, SubscriptionSerializer
from api.services.subscription_planning import subscription_plan
from api.services.subscriptions import detect_subscriptions


class SubscriptionQueryView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SubscriptionSerializer

    def get_queryset(self):
        return Subscription.objects.filter(owner=self.request.user)


class SubscriptionListView(generics.ListAPIView, SubscriptionQueryView):
    pass


class SubscriptionDetectView(SubscriptionQueryView):
    def post(self, request):
        subscriptions = detect_subscriptions(request.user)
        return Response(self.get_serializer(subscriptions, many=True).data)


class SubscriptionDetailView(
    generics.UpdateAPIView, generics.DestroyAPIView, SubscriptionQueryView
):
    http_method_names = ["patch", "delete", "options"]


class SubscriptionPlanningView(SubscriptionQueryView):
    def get(self, request):
        preferences = SubscriptionPreferences.objects.filter(owner=request.user).first()
        if preferences is None:
            preferences = SubscriptionPreferences(owner=request.user)
        inactive = [Subscription.TrackingStatus.PAUSED, Subscription.TrackingStatus.CANCELED]
        records = list(self.get_queryset().exclude(tracking_status__in=inactive))
        return Response(subscription_plan(request.user, records, preferences, timezone.localdate()))


class SubscriptionPreferencesView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SubscriptionPreferencesSerializer

    def get(self, request):
        preferences = SubscriptionPreferences.objects.filter(owner=request.user).first()
        return Response(self.get_serializer(preferences or SubscriptionPreferences(owner=request.user)).data)

    def patch(self, request):
        # Validate before creating a row for a user with default preferences.
        serializer = self.get_serializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        preferences, _ = SubscriptionPreferences.objects.update_or_create(
            owner=request.user, defaults=serializer.validated_data,
        )
        return Response(self.get_serializer(preferences).data)
