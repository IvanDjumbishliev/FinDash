from datetime import timedelta
from decimal import Decimal

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from api.services.copilot_tools import (
    MAX_RANGE_DAYS, DataLimitExceeded, FinancialTools, InvalidToolCall, parse_date,
)


class UserSummaryView(APIView):
    """Provide dashboard insights locally without sending account data to a provider."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request):
        tools = FinancialTools(request.user)
        end = tools.today
        start = end - timedelta(days=29)
        if "from-date" in request.query_params:
            try:
                start = parse_date(request.query_params["from-date"])
                if not 0 <= (end - start).days < MAX_RANGE_DAYS:
                    raise InvalidToolCall("Choose a start date within the last 366 days.")
            except InvalidToolCall as error:
                return Response({"error": str(error)}, status=400)

        try:
            result = tools.get_category_breakdown(start, end)
        except DataLimitExceeded:
            return Response({"error": "Too many records for this range."}, status=422)

        insights = []
        for total in result["totals"][:4]:
            currency = total["currency"]
            description = (
                f"Recorded net spending was {currency} {total['net_spending']} "
                f"across {total['transaction_count']} spending and refund entries "
                f"from {start.isoformat()} through {end.isoformat()}."
            )
            category, amount = max(total["categories"].items(), key=lambda item: Decimal(item[1]))
            if Decimal(amount) > 0:
                description += f" The highest-spending category was {category} ({currency} {amount})."
            insights.append({"title": f"{currency} spending", "description": description})

        return Response(insights, headers={"Cache-Control": "no-store"})
