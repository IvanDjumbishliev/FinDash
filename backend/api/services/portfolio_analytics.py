from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal, localcontext

from api.services.portfolio_history import MAX_LOOKBACK, MarketHistory, company_metadata, historical_data
from api.services.virtual_portfolios import ZERO, decimal_string

BENCHMARKS = {
    "^GSPC": "S&P 500",
    "^IXIC": "Nasdaq Composite",
    "^STOXX50E": "EURO STOXX 50",
    "^FTSE": "FTSE 100",
}
NOTICES = [
    "This report describes simulated, price-only performance. Dividends are omitted.",
    "The positions-only ledger treats buy outlay including fees as contributions and net sell proceeds as withdrawals.",
    "Daily returns assume contributions at the start of the day and withdrawals at the end. Linked returns are a daily time-weighted estimate.",
    "Valuations use observed session closes and recorded trades grouped by exchange date. Missing prices stay blank.",
    "Split-adjusted closes use quantities adjusted from published split ratios. Report adjustments leave the original trade ledger intact.",
    "Benchmarks use same-currency price returns and are rebased on the first shared valued date. Exchange-rate conversion is unavailable.",
]


def daily_return(opening, closing, contribution, withdrawal):
    if opening is None or closing is None or opening + contribution <= 0:
        return None
    ending = closing + withdrawal
    if ending < 0:
        return None
    return ending / (opening + contribution) - 1


def adjusted_quantity(trade, day, market):
    result = trade.quantity
    for split_day, (numerator, denominator) in sorted(market.splits.items()):
        if split_day > day:
            result *= Decimal(numerator) / denominator
    return result


def calculate_series(trades, markets, currency, start, end, today, benchmark):
    by_day = defaultdict(list)
    symbols = set()
    unsupported = set()
    unreconciled = set()
    market_days = set()
    first_sessions = {symbol: min(market.prices, default=None) for symbol, market in markets.items()}
    for trade in trades:
        symbol = trade.ticker
        market = markets.get(symbol, MarketHistory())
        day = trade.timestamp.astimezone(market.zone).date()
        if day > end:
            continue
        symbols.add(symbol)
        first_session = first_sessions.get(symbol)
        if day < today - MAX_LOOKBACK or (first_session and day < first_session - timedelta(days=7)):
            unsupported.add(symbol)
        by_day[day].append(trade)
    for symbol in symbols | ({benchmark} if benchmark else set()):
        market_days.update(markets.get(symbol, MarketHistory()).prices)

    # Replay earlier executions for opening quantities. Keep the most recent
    # observed pre-period session to establish the first return denominator.
    observed = {day for day in market_days | by_day.keys() if day <= end}
    before = max((day for day in observed if day < start), default=None)
    positions = defaultdict(lambda: ZERO)
    rows = []
    factors = {}
    opening = ZERO
    factor = None
    chain_broken = False
    latest_values = None
    for day in sorted(observed):
        contributions = withdrawals = ZERO
        for trade in by_day[day]:
            market = markets.get(trade.ticker, MarketHistory())
            amount = adjusted_quantity(trade, day, market)
            if trade.side == "buy":
                positions[trade.ticker] += amount
                contributions += trade.quantity * trade.price + trade.fees
            else:
                positions[trade.ticker] -= amount
                if positions[trade.ticker] < Decimal("-1e-30"):
                    unreconciled.add(trade.ticker)
                proceeds = trade.quantity * trade.price - trade.fees
                withdrawals += max(ZERO, proceeds)
                contributions += max(ZERO, -proceeds)
        if day < start and day != before:
            continue

        values = {}
        missing = {}
        for ticker, amount in sorted(positions.items()):
            if ticker in unreconciled:
                missing[ticker] = "unreconciled_shares"
                continue
            if abs(amount) < Decimal("1e-30"):
                continue
            market = markets.get(ticker, MarketHistory())
            if ticker in unsupported:
                missing[ticker] = "split_history_outside_coverage"
            elif market.status != "available":
                missing[ticker] = market.status
            elif market.currency != currency:
                missing[ticker] = "currency_mismatch"
            elif market.prices.get(day) is None:
                missing[ticker] = "missing_close"
            else:
                values[ticker] = amount * market.prices[day]
        closing = None if missing else sum(values.values(), ZERO)
        if day < start:
            opening = closing
            if closing and closing > 0:
                factor = Decimal(1)
            continue
        change = daily_return(opening, closing, contributions, withdrawals)
        if factor is not None and (closing is None or opening is None and change is None):
            chain_broken = True
        if not chain_broken:
            if change is not None:
                factor = (factor if factor is not None else Decimal(1)) * (1 + change)
            elif closing is not None and closing > 0 and factor is None:
                factor = Decimal(1)
        benchmark_market = markets.get(benchmark, MarketHistory())
        benchmark_price = benchmark_market.prices.get(day) if (
            benchmark_market.status == "available" and benchmark_market.currency == currency
        ) else None
        published = factor if not chain_broken and closing is not None else None
        factors[day.isoformat()] = (published, benchmark_price)
        rows.append({
            "date": day.isoformat(), "value": decimal_string(closing),
            "contributions": decimal_string(contributions), "withdrawals": decimal_string(withdrawals),
            "daily_return": decimal_string(change),
            "cumulative_return": decimal_string(published - 1) if published is not None else None,
            "benchmark_price": decimal_string(benchmark_price),
            "missing_prices": missing,
        })
        opening = closing
        latest_values = None if missing else values

    align_benchmark(rows, factors)
    return rows, latest_values, symbols


def align_benchmark(rows, factors):
    base = None
    previous_price = None
    for row in rows:
        factor, price = factors[row["date"]]
        if base is None and factor is not None and factor > 0 and price is not None and Decimal(row["value"]) > 0:
            base = (factor, price)
        if base is None or factor is None or price is None:
            row.update(aligned_portfolio_return=None, benchmark_return=None, benchmark_daily_return=None)
            previous_price = None
            continue
        row.update(
            aligned_portfolio_return=decimal_string(factor / base[0] - 1),
            benchmark_return=decimal_string(price / base[1] - 1),
            benchmark_daily_return=decimal_string(price / previous_price - 1) if previous_price is not None else None,
        )
        previous_price = price


def allocation(values, markets, as_of):
    if values is None or not values:
        return {"as_of": as_of, "available": values is not None, "companies": [], "sectors": [], "concentration": None}
    tickers = sorted(values)
    with ThreadPoolExecutor(max_workers=min(5, len(tickers))) as pool:
        metadata = list(pool.map(lambda ticker: company_metadata(ticker, markets[ticker]), tickers))
    companies = defaultdict(lambda: ZERO)
    sectors = defaultdict(lambda: ZERO)
    for ticker, (company, sector) in zip(tickers, metadata, strict=True):
        companies[company or ticker] += values[ticker]
        sectors[sector or "Unknown sector"] += values[ticker]
    total = sum(values.values(), ZERO)
    company_weights = sorted(companies.values(), reverse=True)
    sector_weights = [amount for label, amount in sectors.items() if label != "Unknown sector"]

    def group(mapping):
        return [
            {"label": label, "value": decimal_string(amount), "weight": decimal_string(amount / total)}
            for label, amount in sorted(mapping.items(), key=lambda item: (-item[1], item[0]))
        ]

    return {
        "as_of": as_of, "available": True, "companies": group(companies), "sectors": group(sectors),
        "concentration": {
            "top_company_weight": decimal_string(company_weights[0] / total),
            "top_three_company_weight": decimal_string(sum(company_weights[:3], ZERO) / total),
            "company_hhi": decimal_string(sum(((amount / total) ** 2 for amount in company_weights), ZERO)),
            "largest_known_sector_weight": decimal_string(max(sector_weights) / total) if sector_weights else None,
            "unknown_sector_weight": decimal_string(sectors.get("Unknown sector", ZERO) / total),
        },
    }


def build_analytics(portfolio, start, end, today, benchmark=None):
    trades = list(portfolio.trades.filter(timestamp__date__lte=end + timedelta(days=1)).order_by("pk"))
    cutoff = today - MAX_LOOKBACK
    symbol_starts = {}
    for trade in trades:
        on = trade.timestamp.date()
        symbol_starts[trade.ticker] = max(cutoff, min(symbol_starts.get(trade.ticker, start - timedelta(days=10)), on))
    if benchmark:
        symbol_starts[benchmark] = max(cutoff, start - timedelta(days=10))
    markets = historical_data(symbol_starts, today)

    with localcontext() as context:
        context.prec = 60
        rows, latest_values, symbols = calculate_series(trades, markets, portfolio.currency, start, end, today, benchmark)
        distribution = allocation(latest_values, markets, rows[-1]["date"] if rows else None)

    coverage = {}
    for ticker in sorted(symbols | ({benchmark} if benchmark else set())):
        market = markets[ticker]
        closed = [day for day, amount in market.prices.items() if amount is not None and day <= end]
        coverage[ticker] = {
            "currency": market.currency, "status": (
                "currency_mismatch" if market.status == "available" and market.currency != portfolio.currency
                else market.status
            ),
            "last_close": max(closed).isoformat() if closed else None,
            "retrieved_at": market.retrieved_at,
        }
    aligned = [row for row in rows if row["benchmark_return"] is not None]
    return {
        "currency": portfolio.currency, "start": start.isoformat(), "end": end.isoformat(), "is_virtual": True,
        "benchmark": {"symbol": benchmark, "label": BENCHMARKS[benchmark],
                      "aligned_from": aligned[0]["date"] if aligned else None} if benchmark else None,
        "history": rows, "allocation": distribution, "coverage": coverage,
        "first_return_date": next((row["date"] for row in rows if row["cumulative_return"] is not None), None),
        "missing_valuation_days": sum(row["value"] is None for row in rows),
        "notices": NOTICES,
    }
