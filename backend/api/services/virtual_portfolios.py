from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_EVEN, localcontext

from django.db import transaction
from django.db.models import F

from api.models import Portfolio, VirtualTrade

ZERO = Decimal(0)
BASIS_PRECISION = Decimal("0.0000000000000001")


class PortfolioNotFound(Exception):
    pass


class InvalidTrade(ValueError):
    pass


class DuplicateOrder(InvalidTrade):
    pass


def decimal_string(value):
    if value is None:
        return None
    if not value:
        return "0"
    return format(value, "f").rstrip("0").rstrip(".") if value.as_tuple().exponent < 0 else format(value, "f")


@transaction.atomic
def record_trade(owner, portfolio_id, **terms):
    # A write lock before the ownership check and position read serializes appends,
    # including on SQLite where select_for_update is a no-op.
    updated = Portfolio.objects.filter(pk=portfolio_id, owner=owner).update(
        ledger_version=F("ledger_version") + 1,
    )
    if not updated:
        raise PortfolioNotFound
    portfolio = Portfolio.objects.get(pk=portfolio_id, owner=owner)
    terms.setdefault("currency", portfolio.currency)
    terms.setdefault("fees", ZERO)
    if terms["currency"] != portfolio.currency:
        raise InvalidTrade("Trade currency must match the portfolio currency.")

    order_id = terms.get("client_order_id")
    if order_id:
        previous = portfolio.trades.filter(client_order_id=order_id).first()
        if previous:
            if any(getattr(previous, key) != value for key, value in terms.items()):
                raise DuplicateOrder("This client order ID already has different trade terms.")
            # Replays leave the ledger version and trades unchanged.
            transaction.set_rollback(True)
            return previous, False

    if terms["side"] == VirtualTrade.Side.SELL:
        with localcontext() as context:
            context.prec = 60
            holdings = portfolio.trades.filter(ticker=terms["ticker"]).values_list("side", "quantity")
            available = sum((
                quantity if side == VirtualTrade.Side.BUY else -quantity
                for side, quantity in holdings.iterator()
            ), ZERO)
        if available < terms["quantity"]:
            raise InvalidTrade("The sale exceeds the virtual quantity held.")
    return VirtualTrade.objects.create(portfolio=portfolio, **terms), True


@dataclass
class Lot:
    quantity: Decimal
    basis: Decimal


@dataclass
class Position:
    quantity: Decimal = ZERO
    cost_basis: Decimal = ZERO
    realized_pnl: Decimal = ZERO
    fees: Decimal = ZERO
    lots: deque = field(default_factory=deque)


def fifo_positions(trades):
    positions = {}
    with localcontext() as context:
        context.prec = 60
        for trade in trades:
            position = positions.setdefault(trade.ticker, Position())
            position.fees += trade.fees
            if trade.side == VirtualTrade.Side.BUY:
                basis = trade.quantity * trade.price + trade.fees
                position.lots.append(Lot(trade.quantity, basis))
                position.cost_basis += basis
                position.quantity += trade.quantity
                continue

            if trade.quantity > position.quantity:
                raise InvalidTrade("The virtual trade ledger is inconsistent.")
            unsold = trade.quantity
            released = ZERO
            while unsold:
                lot = position.lots[0]
                if unsold >= lot.quantity:
                    unsold -= lot.quantity
                    released += lot.basis
                    position.lots.popleft()
                else:
                    allocated = (lot.basis * unsold / lot.quantity).quantize(BASIS_PRECISION, rounding=ROUND_HALF_EVEN)
                    released += allocated
                    lot.basis -= allocated
                    lot.quantity -= unsold
                    unsold = ZERO
            position.cost_basis -= released
            position.quantity -= trade.quantity
            position.realized_pnl += trade.quantity * trade.price - trade.fees - released
    return positions


def portfolio_snapshot(portfolio, quotes_for):
    positions = fifo_positions(portfolio.trades.order_by("pk").iterator())
    quotes = quotes_for(sorted(ticker for ticker, item in positions.items() if item.quantity))
    holdings = []
    by_ticker = []
    priced_value = priced_unrealized = ZERO
    valued = 0
    with localcontext() as context:
        context.prec = 60
        for ticker, position in sorted(positions.items()):
            identity = {
                "ticker": ticker,
                "quantity": decimal_string(position.quantity),
                "cost_basis": decimal_string(position.cost_basis),
                "realized_pnl": decimal_string(position.realized_pnl),
                "fees": decimal_string(position.fees),
            }
            by_ticker.append(identity)
            if not position.quantity:
                continue

            quote = quotes.get(ticker, {"status": "unavailable"})
            quote_status = quote["status"]
            market_value = unrealized = None
            if quote_status == "quoted":
                if quote["currency"] != portfolio.currency:
                    quote_status = "currency_mismatch"
                else:
                    market_value = quote["price"] * position.quantity
                    unrealized = market_value - position.cost_basis
                    valued += 1
                    priced_value += market_value
                    priced_unrealized += unrealized
            holdings.append({
                **identity,
                "average_cost_per_share": decimal_string(
                    (position.cost_basis / position.quantity).quantize(BASIS_PRECISION, rounding=ROUND_HALF_EVEN),
                ),
                "market_quote": {
                    "status": quote_status,
                    "price": decimal_string(quote.get("price")),
                    "currency": quote.get("currency"),
                    "timestamp": quote.get("timestamp"),
                },
                "market_value": decimal_string(market_value),
                "unrealized_pnl": decimal_string(unrealized),
            })

        complete = valued == len(holdings)
        realized = sum((item.realized_pnl for item in positions.values()), ZERO)
        performance = {
            "open_position_count": len(holdings),
            "valued_position_count": valued,
            "valuation_complete": complete,
            "open_cost_basis": decimal_string(sum((item.cost_basis for item in positions.values()), ZERO)),
            "fees": decimal_string(sum((item.fees for item in positions.values()), ZERO)),
            "realized_pnl": decimal_string(realized),
            "market_value": decimal_string(priced_value) if complete else None,
            "unrealized_pnl": decimal_string(priced_unrealized) if complete else None,
            "total_pnl": decimal_string(realized + priced_unrealized) if complete else None,
            "priced_market_value": decimal_string(priced_value),
            "priced_unrealized_pnl": decimal_string(priced_unrealized),
        }
    return holdings, performance, by_ticker
