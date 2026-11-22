from django.db import DatabaseError
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.services.forecasting import HORIZONS, ForecastDataLimit, build_cash_flow_forecast


class ForecastQuery(serializers.Serializer):
    horizon = serializers.ChoiceField(choices=HORIZONS, default=30)
    currency = serializers.RegexField(r"\A[A-Za-z]{3}\Z", required=False)
    starting_balance = serializers.DecimalField(max_digits=14, decimal_places=2, required=False)

    def validate_currency(self, value):
        return value.upper()


class ForecastDisplayQuery(ForecastQuery):
    summary_only = serializers.BooleanField(default=False)


class CashFlowForecastView(APIView):
    permission_classes = [IsAuthenticated]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response

    def get(self, request):
        params = request.query_params.copy()
        balance = request.headers.get("X-Starting-Balance")
        if balance is not None:
            if "starting_balance" in params:
                raise serializers.ValidationError({"starting_balance": "Supply the balance once."})
            params["starting_balance"] = balance

        serializer = ForecastDisplayQuery(data=params)
        serializer.is_valid(raise_exception=True)
        try:
            result = build_cash_flow_forecast(request.user, **serializer.validated_data)
        except ForecastDataLimit:
            return Response({"error": "Recorded activity exceeds the forecast processing limit."}, status=422)
        except DatabaseError:
            return Response({"error": "The forecast is temporarily unavailable."}, status=503)
        return Response(result)
