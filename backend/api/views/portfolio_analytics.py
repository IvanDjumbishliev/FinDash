import csv
from datetime import UTC, timedelta

from django.db import DatabaseError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.response import Response

from api.models import Portfolio
from api.services.portfolio_analytics import BENCHMARKS, build_analytics
from api.services.portfolio_history import MAX_LOOKBACK

from .assistant import PrivateCopilotView

MAX_DAYS = 366
CSV_FIELDS = (
    "date", "value", "contributions", "withdrawals", "daily_return", "cumulative_return",
    "aligned_portfolio_return", "benchmark_price", "benchmark_return", "benchmark_daily_return",
)


class AnalyticsQuery(serializers.Serializer):
    start = serializers.DateField(required=False)
    end = serializers.DateField(required=False)
    benchmark = serializers.ChoiceField(choices=tuple(BENCHMARKS), required=False)


class PortfolioAnalyticsView(PrivateCopilotView):
    def get(self, request, pk):
        portfolio = get_object_or_404(Portfolio.objects.filter(owner=request.user), pk=pk)
        query = AnalyticsQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        today = timezone.now().astimezone(UTC).date()
        end = query.validated_data.get("end", today - timedelta(days=1))
        if not today - MAX_LOOKBACK <= end < today:
            raise serializers.ValidationError({"end": "Choose a completed day within the supported market history window."})
        start = query.validated_data.get("start", max(end - timedelta(days=29), today - MAX_LOOKBACK))
        if not today - MAX_LOOKBACK <= start <= end or (end - start).days >= MAX_DAYS:
            raise serializers.ValidationError({"start": "Choose a range of up to 366 completed days within the supported window."})
        try:
            report = build_analytics(portfolio, start, end, today, query.validated_data.get("benchmark"))
        except DatabaseError:
            return Response({"error": "Portfolio analytics are temporarily unavailable."}, status=503)
        return self.render_report(report)

    def render_report(self, report):
        return Response(report)


class PortfolioAnalyticsExportView(PortfolioAnalyticsView):
    def render_report(self, report):
        response = HttpResponse(content_type="text/csv; charset=utf-8", headers={
            "Content-Disposition": f'attachment; filename="virtual-portfolio-{report["start"]}-{report["end"]}.csv"',
            "X-Content-Type-Options": "nosniff",
        })
        writer = csv.writer(response)
        writer.writerow([*CSV_FIELDS, "currency", "benchmark", "missing_prices", "is_virtual"])
        for row in report["history"]:
            writer.writerow([
                *(row[field] for field in CSV_FIELDS), report["currency"],
                report["benchmark"]["symbol"] if report["benchmark"] else "",
                "; ".join(f"{ticker}:{reason}" for ticker, reason in row["missing_prices"].items()),
                True,
            ])
        return response
