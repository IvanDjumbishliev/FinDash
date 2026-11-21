from datetime import date, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import UserProfile
from api.services.spending_heatmap import daily_spending

MAX_DAYS = 366


class HeatmapQuerySerializer(serializers.Serializer):
    start = serializers.DateField(required=False, input_formats=["%Y-%m-%d"])
    end = serializers.DateField(required=False, input_formats=["%Y-%m-%d"])
    currency = serializers.RegexField(r"\A[A-Za-z]{3}\Z", required=False)


class ProfileTimezoneSerializer(serializers.Serializer):
    timezone = serializers.CharField(max_length=255)

    def validate_timezone(self, value):
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise serializers.ValidationError("Enter a valid IANA timezone.") from error
        return value


class ProfileTimezoneView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = getattr(request.user, "userprofile", None)
        return Response({"timezone": profile.timezone if profile else "UTC"})

    def patch(self, request):
        serializer = ProfileTimezoneSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        UserProfile.objects.update_or_create(user=request.user, defaults=serializer.validated_data)
        return Response(serializer.validated_data)


class SpendingHeatmapView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = HeatmapQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        query = serializer.validated_data
        profile = getattr(request.user, "userprofile", None)
        zone = ZoneInfo(profile.timezone if profile else "UTC")
        currency = query.get("currency", profile.currency if profile else "USD").upper()
        end = query.get("end", timezone.localdate(timezone=zone))
        start = query.get("start", end - timedelta(days=min(MAX_DAYS - 1, end.toordinal() - 1)))
        if start > end:
            raise ValidationError({"start": "Start must be on or before end."})
        if (end - start).days >= MAX_DAYS:
            raise ValidationError({"end": "Choose a range of up to 366 days."})
        if start == date.min or end == date.max:
            raise ValidationError({"detail": "The range must have representable timezone boundaries."})

        return Response({
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timezone": zone.key,
            "currency": currency,
            "days": daily_spending(request.user, start, end, zone, currency),
        })
