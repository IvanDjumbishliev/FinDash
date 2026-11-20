from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from api.models import Subscription
from api.serializers import SubscriptionSerializer
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
