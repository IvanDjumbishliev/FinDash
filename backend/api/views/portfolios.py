import re
from decimal import Decimal

from django.db import DatabaseError
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.response import Response

from api.models import Portfolio, VirtualTrade
from api.services.portfolio_quotes import portfolio_quotes
from api.services.virtual_portfolios import (
    DuplicateOrder, InvalidTrade, PortfolioNotFound, portfolio_snapshot, record_trade,
)

from .assistant import PrivateCopilotView

BASIS = "FIFO"
NOTICES = [
    "Trades are simulated at the execution prices entered by the user.",
    "Buy fees are included in cost basis and sell fees reduce sale proceeds.",
    "Market quotes may be delayed. Full unrealized P/L requires a usable same-currency quote for every holding.",
    "Splits and dividends are not applied because this ledger has no verified corporate-action feed.",
    "The virtual ledger models positions and P/L without cash balances or FX conversion.",
]


class CurrencyField(serializers.RegexField):
    def __init__(self, **kwargs):
        super().__init__(r"\A[A-Za-z]{3}\Z", **kwargs)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if not value.isascii():
            self.fail("invalid")
        return value.upper()


class PortfolioSerializer(serializers.ModelSerializer):
    currency = CurrencyField(default="USD")
    is_virtual = serializers.BooleanField(read_only=True)

    class Meta:
        model = Portfolio
        fields = ("id", "name", "currency", "is_virtual", "created_at")
        read_only_fields = ("id", "is_virtual", "created_at")


class VirtualTradeSerializer(serializers.ModelSerializer):
    currency = CurrencyField(required=False)
    ticker = serializers.CharField(max_length=10)
    quantity = serializers.DecimalField(max_digits=18, decimal_places=8, min_value=Decimal("0.00000001"))
    price = serializers.DecimalField(max_digits=18, decimal_places=8, min_value=Decimal("0.00000001"))
    fees = serializers.DecimalField(max_digits=18, decimal_places=8, min_value=Decimal(0), default=Decimal(0))

    class Meta:
        model = VirtualTrade
        fields = ("id", "timestamp", "ticker", "side", "quantity", "price", "fees", "currency", "client_order_id")
        read_only_fields = ("id", "timestamp")

    def validate_ticker(self, value):
        if not re.fullmatch(r"[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*", value):
            raise serializers.ValidationError("Enter a valid equity ticker.")
        return value.upper()


class PortfolioListView(PrivateCopilotView):
    def get(self, request):
        portfolios = Portfolio.objects.filter(owner=request.user)
        return Response(PortfolioSerializer(portfolios, many=True).data)

    def post(self, request):
        serializer = PortfolioSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        portfolio = serializer.save(owner=request.user)
        return Response(PortfolioSerializer(portfolio).data, status=201)


class PortfolioTradeView(PrivateCopilotView):
    def post(self, request, pk):
        serializer = VirtualTradeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            trade, created = record_trade(request.user, pk, **serializer.validated_data)
        except PortfolioNotFound:
            return Response({"error": "Portfolio not found."}, status=404)
        except DuplicateOrder as error:
            return Response({"error": str(error)}, status=409)
        except InvalidTrade as error:
            return Response({"error": str(error)}, status=400)
        except DatabaseError:
            return Response({"error": "The virtual ledger is temporarily unavailable."}, status=503)
        return Response({**VirtualTradeSerializer(trade).data, "is_virtual": True}, status=201 if created else 200)


class PortfolioSnapshotView(PrivateCopilotView):
    def get(self, request, pk):
        portfolio = get_object_or_404(Portfolio.objects.filter(owner=request.user), pk=pk)
        try:
            holdings, performance, tickers = portfolio_snapshot(portfolio, portfolio_quotes)
        except (DatabaseError, InvalidTrade):
            return Response({"error": "The virtual ledger could not be read."}, status=503)
        return Response({
            "portfolio": PortfolioSerializer(portfolio).data,
            "cost_basis_method": BASIS,
            "notices": NOTICES,
            **self.details(holdings, performance, tickers),
        })


class PortfolioHoldingsView(PortfolioSnapshotView):
    def details(self, holdings, performance, tickers):
        return {"holdings": holdings, "valuation_complete": performance["valuation_complete"]}


class PortfolioPerformanceView(PortfolioSnapshotView):
    def details(self, holdings, performance, tickers):
        return {"performance": performance, "by_ticker": tickers}
