import math

from rest_framework import views, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from api.models import Stock
import yfinance as yf


def _stock_info(symbol):
    info = yf.Ticker(symbol).info
    if not isinstance(info, dict):
        return None

    name = info.get("longName") or info.get("shortName")
    if not name:
        return None

    return {
        "symbol": str(info.get("symbol") or symbol).upper(),
        "name": name,
        "exchange": info.get("exchange") or "Unknown",
    }


class WatchlistView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        stocks = Stock.objects.filter(user=request.user).values("ticker", "name")
        watchlist = []
        for stock in stocks:
            try:
                ticker = yf.Ticker(stock["ticker"])
                hist = ticker.history(period="1mo", interval="1d", actions=False)
                if hist is None or hist.empty:
                    watchlist.append(
                        {
                            "symbol": stock["ticker"],
                            "name": stock["name"],
                            "history": [],
                            "error": "No data available for this ticker right now.",
                        }
                    )
                    continue

                history = [
                    {"date": index.strftime("%Y-%m-%d"), "price": float(row["Close"])}
                    for index, row in hist.iterrows()
                    if math.isfinite(float(row["Close"]))
                ]
                if not history:
                    watchlist.append(
                        {
                            "symbol": stock["ticker"],
                            "name": stock["name"],
                            "history": [],
                            "error": "No data available for this ticker right now.",
                        }
                    )
                    continue

                watchlist.append(
                    {
                        "symbol": stock["ticker"],
                        "name": stock["name"],
                        "history": history,
                    }
                )
            except Exception:
                watchlist.append(
                    {
                        "symbol": stock["ticker"],
                        "name": stock["name"],
                        "history": [],
                        "error": "No data available for this ticker right now.",
                    }
                )

        return Response({"stocks": watchlist})

    def post(self, request):
        user = request.user
        new_symbol = request.data.get("symbol")

        if not isinstance(new_symbol, str) or not new_symbol.strip():
            return Response(
                {"error": "Symbol is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        new_symbol = new_symbol.strip().upper()
        try:
            stock_info = _stock_info(new_symbol)
            if stock_info is None:
                return Response(
                    {"error": f"No data available for ticker {new_symbol}."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            Stock.objects.get_or_create(
                user=user,
                ticker=stock_info["symbol"],
                defaults={
                    "name": stock_info["name"],
                    "quantity": 0,  # Just for watchlist, not owned
                    "price_per_share": 0,  # Just for watchlist, not owned
                },
            )

            stocks = Stock.objects.filter(user=user).values("ticker", "name")
            return Response(
                {"symbols": [stock["ticker"] for stock in stocks]},
                status=status.HTTP_200_OK,
            )

        except Exception:
            return Response(
                {
                    "error": (
                        f"Unable to fetch data for ticker {new_symbol} right now."
                    )
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )


class StockSearchView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = (request.GET.get("query") or "").strip().upper()
        if len(query) < 2:
            return Response(
                {"error": "Enter a ticker with at least two characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            stock_info = _stock_info(query)
            if stock_info is None:
                return Response(
                    {"error": f"No data available for ticker {query}."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            return Response([stock_info])
        except Exception:
            return Response(
                {"error": f"Unable to fetch ticker {query} right now."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
