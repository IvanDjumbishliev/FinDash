from collections import defaultdict
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from random import Random

from django.utils import timezone

from api.models import Subscription, Transaction
from api.services.budgets import CENT, INTERNAL_TRANSFER, REFUND, ZERO
from api.services.copilot_tools import account_timezone, currency_code, money
from api.services.forecast_recurrence import LedgerEntry, recurring_schedules
from api.services.subscriptions import merchant_names

HORIZONS = (30, 60, 90)
LOOKBACK_DAYS = 1096
BASELINE_WEEKS = 26
MIN_BASELINE_WEEKS = 8
MIN_SCENARIO_WEEKS = 16
MIN_SCENARIO_VARIABLE_WEEKS = 8
MAX_LEDGER_ROWS = 40_000
MAX_SUBSCRIPTIONS = 500
MAX_EVENTS = 10_000

ASSUMPTIONS = [
    "Dates use the account timezone. The forecast starts tomorrow, after the supplied starting balance date.",
    "Only the selected currency is included. Identified internal transfers are excluded; recognized refunds reduce expenses.",
    "Confirmed active subscriptions use their stored estimates. Historical patterns use similar amounts and repeated payment dates.",
    "The variable estimate averages recent completed weeks after capping the extremes of each cash-flow component.",
    "Variable estimates are spread evenly between dates; recurring estimates are placed on their expected dates.",
]

LIMITATIONS = [
    "Recorded transactions can omit accounts or dates. A quiet week means no recorded activity, not verified zero cash flow.",
    "FinDash uses only the supplied starting balance; ledger history does not establish a bank balance.",
    "Budget limits are planning targets rather than expected charges.",
    "Timing and amounts may change. The scenario range varies historical variable cash flow and holds scheduled amounts fixed.",
    "Scenario percentiles are illustrative and have no calibrated probability of covering future outcomes.",
]


class ForecastDataLimit(ValueError):
    pass


def cents(amount):
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def read_ledger(owner, start, end, zone, currency):
    rows = Transaction.objects.filter(
        user=owner, currency__iexact=currency,
        timestamp__gte=datetime.combine(start - timedelta(days=1), time.min, UTC),
        timestamp__lte=datetime.combine(end + timedelta(days=1), time.max, UTC),
    ).order_by().values_list("pk", "timestamp", "amount", "particulars", "merchant", "normalized_merchant", "category")

    result = []
    for index, (pk, timestamp, amount, description, merchant, normalized, category) in enumerate(
        rows[:MAX_LEDGER_ROWS + 1].iterator()
    ):
        if index == MAX_LEDGER_ROWS:
            raise ForecastDataLimit
        day = timestamp.astimezone(zone).date()
        if not start <= day <= end or not amount or INTERNAL_TRANSFER.search(description):
            continue
        if amount < 0:
            kind = "expense"
        else:
            kind = "refund" if REFUND.search(description) else "income"
        label, identity = merchant_names(merchant or description)
        _, stored_identity = merchant_names(normalized)
        result.append(LedgerEntry(pk, day, abs(amount), kind, label, stored_identity or identity, category))
    return result


def cash_components(entries):
    totals = defaultdict(lambda: ZERO)
    for entry in entries:
        totals[entry.kind] += entry.amount
    return totals


def cap_extremes(values):
    ordered = sorted(values)
    tail = max(1, len(ordered) // 10)
    lower, upper = ordered[tail], ordered[-tail - 1]
    return [min(upper, max(lower, value)) for value in values]


def weekly_baseline(ledger, recurring_ids, as_of):
    first = min((entry.day for entry in ledger), default=as_of)
    week_count = min(BASELINE_WEEKS, (as_of - first).days // 7)
    start = as_of - timedelta(weeks=week_count)
    active = set()
    variable_active = set()
    income = [ZERO] * week_count
    expenses = [ZERO] * week_count
    for entry in ledger:
        if not start <= entry.day < as_of:
            continue
        week = (entry.day - start).days // 7
        active.add(week)
        if entry.id in recurring_ids:
            continue
        variable_active.add(week)
        if entry.kind == "income":
            income[week] += entry.amount
        else:
            expenses[week] += entry.amount if entry.kind == "expense" else -entry.amount

    coverage = {
        "start_date": start.isoformat() if week_count else None,
        "end_date": (as_of - timedelta(days=1)).isoformat() if week_count else None,
        "complete_weeks": week_count,
        "weeks_with_recorded_activity": len(active),
        "weeks_with_variable_activity": len(variable_active),
    }
    enough = week_count >= MIN_BASELINE_WEEKS and len(active) * 2 >= week_count
    if not enough:
        return coverage, None
    return coverage, list(zip(cap_extremes(income), cap_extremes(expenses), strict=True))


def variable_category_rates(ledger, recurring_ids, as_of, week_count):
    start = as_of - timedelta(weeks=week_count)
    totals = defaultdict(lambda: [ZERO] * week_count)
    for entry in ledger:
        if start <= entry.day < as_of and entry.id not in recurring_ids and entry.kind in ("expense", "refund"):
            index = (entry.day - start).days // 7
            totals[entry.category][index] += entry.amount if entry.kind == "expense" else -entry.amount
    rates = {key: cents(sum(cap_extremes(values), ZERO) / week_count) for key, values in totals.items()}
    return {key: money(value) for key, value in sorted(rates.items()) if value > ZERO and key in Transaction.Category.values}


def historical_weeks(ledger, as_of):
    if not ledger:
        return []
    start = max(as_of - timedelta(days=90), min(entry.day for entry in ledger))
    # Partition backward from the forecast boundary. The earliest week can be partial.
    buckets = defaultdict(list)
    for entry in ledger:
        if entry.day >= start:
            buckets[(as_of - entry.day).days // 7].append(entry)
    result = []
    for index in range((as_of - start).days // 7, -1, -1):
        end = as_of - timedelta(weeks=index)
        totals = cash_components(buckets[index])
        expenses = totals["expense"] - totals["refund"]
        result.append({
            "start_date": max(start, end - timedelta(days=6)).isoformat(),
            "end_date": end.isoformat(),
            "transaction_count": len(buckets[index]),
            "income": money(totals["income"]),
            "net_expenses": money(expenses),
            "net_cash_flow": money(totals["income"] - expenses),
        })
    return result


def historical_scenarios(weeks, days, starting_balance):
    if len(weeks) < MIN_SCENARIO_WEEKS:
        return None
    nets = [int((income - expenses) * 100) for income, expenses in weeks]
    if len(set(nets)) < 2:
        return None

    # Use the same contiguous two-week samples at every point on the forecast path.
    # Integer sevenths of a cent preserve precision when distributing weekly amounts.
    rng = Random(0)
    samples = [[] for _ in days]
    for _ in range(1000):
        cumulative = 0
        for start in range(0, len(days), 14):
            index = rng.randrange(len(nets) - 1)
            for offset, weekly_net in enumerate(nets[index:index + 2]):
                position = start + offset * 7
                elapsed = max(0, min(7, len(days) - position))
                for day in range(elapsed):
                    samples[position + day].append(cumulative + weekly_net * (day + 1))
                cumulative += weekly_net * elapsed

    path = []
    fixed = ZERO
    for point, values in zip(days, samples, strict=True):
        fixed += Decimal(point["scheduled_income"]) - Decimal(point["scheduled_expenses"])
        values.sort()
        low, high = (cents(fixed + Decimal(values[index]) / 700) for index in (99, 899))
        path.append({
            "date": point["date"],
            "net_cash_flow": {"lower": money(low), "upper": money(high)},
            "ending_balance": None if starting_balance is None else {
                "lower": money(starting_balance + low), "upper": money(starting_balance + high),
            },
        })
    last = path[-1]
    if last["net_cash_flow"]["lower"] == last["net_cash_flow"]["upper"]:
        return None
    return {
        "method": "historical_two_week_block_bootstrap",
        "label": "Historical scenario range",
        "lower_percentile": 10,
        "upper_percentile": 90,
        "net_cash_flow": last["net_cash_flow"],
        "ending_balance": last["ending_balance"],
        "days": path,
    }


def forecast_events(schedules, start, end):
    events = []
    totals = defaultdict(lambda: {"income": ZERO, "expense": ZERO})
    event_count = 0
    for schedule in schedules:
        dates = list(schedule.dates(start, end))
        if not dates:
            continue
        event_count += len(dates)
        if event_count > MAX_EVENTS:
            raise ForecastDataLimit
        for day in dates:
            totals[day][schedule.kind] += schedule.amount
        events.append({
            "label": schedule.label, "kind": schedule.kind, "amount": money(schedule.amount),
            "frequency": schedule.frequency, "source": schedule.source,
            "observations": schedule.observations, "dates": [day.isoformat() for day in dates],
            **({"subscription_id": schedule.subscription_id} if schedule.subscription_id is not None else {}),
        })
    return totals, sorted(events, key=lambda event: (event["dates"][0], event["kind"], event["label"]))


def project_days(start, horizon, scheduled, weeks, starting_balance):
    weekly_income, weekly_expenses = (None, None) if weeks is None else [
        sum(column, ZERO) / len(weeks) for column in zip(*weeks, strict=True)
    ]
    days = []
    fixed_income = fixed_expenses = variable_income = variable_expenses = ZERO
    for offset in range(horizon):
        day = start + timedelta(days=offset)
        fixed = scheduled[day]
        fixed_income += fixed["income"]
        fixed_expenses += fixed["expense"]
        daily_income = daily_expenses = net = balance = None
        if weeks is not None:
            next_income = cents(weekly_income * (offset + 1) / 7)
            next_expenses = cents(weekly_expenses * (offset + 1) / 7)
            daily_income, daily_expenses = next_income - variable_income, next_expenses - variable_expenses
            variable_income, variable_expenses = next_income, next_expenses
            net = fixed["income"] - fixed["expense"] + daily_income - daily_expenses
            if starting_balance is not None:
                balance = starting_balance + fixed_income - fixed_expenses + variable_income - variable_expenses
        days.append({
            "date": day.isoformat(),
            "scheduled_income": money(fixed["income"]),
            "scheduled_expenses": money(fixed["expense"]),
            "estimated_variable_income": money(daily_income) if daily_income is not None else None,
            "estimated_variable_expenses": money(daily_expenses) if daily_expenses is not None else None,
            "estimated_net_cash_flow": money(net) if net is not None else None,
            "estimated_balance": money(balance) if balance is not None else None,
        })

    fixed_net = fixed_income - fixed_expenses
    net = None if weeks is None else fixed_net + variable_income - variable_expenses
    summary = {
        "scheduled_income": money(fixed_income),
        "scheduled_expenses": money(fixed_expenses),
        "scheduled_net_cash_flow": money(fixed_net),
        "estimated_variable_income": money(variable_income) if weeks is not None else None,
        "estimated_variable_expenses": money(variable_expenses) if weeks is not None else None,
        "estimated_net_cash_flow": money(net) if net is not None else None,
        "scheduled_only_ending_balance": money(starting_balance + fixed_net) if starting_balance is not None else None,
        "estimated_ending_balance": money(starting_balance + net) if starting_balance is not None and net is not None else None,
    }
    return days, summary


def build_cash_flow_forecast(
    owner, *, horizon=30, currency=None, starting_balance=None, as_of=None, include_uncertainty=True,
):
    """Estimate cash flow from the owner's recorded ledger, independent of HTTP."""
    if horizon not in HORIZONS:
        raise ValueError("Unsupported forecast horizon.")
    zone = account_timezone(owner)
    as_of = as_of or timezone.localdate(timezone=zone)
    profile = getattr(owner, "userprofile", None)
    currency = currency or (currency_code(profile.currency) if profile else None) or "USD"
    history_start = as_of - timedelta(days=LOOKBACK_DAYS - 1)
    start, end = as_of + timedelta(days=1), as_of + timedelta(days=horizon)

    ledger = read_ledger(owner, history_start, as_of, zone, currency)
    subscriptions = list(Subscription.objects.filter(
        owner=owner, currency__iexact=currency,
    ).order_by("pk")[:MAX_SUBSCRIPTIONS + 1])
    if len(subscriptions) > MAX_SUBSCRIPTIONS:
        raise ForecastDataLimit

    schedules, recurring_ids = recurring_schedules(ledger, subscriptions, as_of)
    scheduled, events = forecast_events(schedules, start, end)
    coverage, weeks = weekly_baseline(ledger, recurring_ids, as_of)
    days, totals = project_days(start, horizon, scheduled, weeks, starting_balance)
    previous = cash_components(ledger)
    first, last = min((item.day for item in ledger), default=None), max((item.day for item in ledger), default=None)
    uncertainty = None
    if include_uncertainty and weeks is not None and coverage["weeks_with_variable_activity"] >= MIN_SCENARIO_VARIABLE_WEEKS:
        uncertainty = historical_scenarios(weeks, days, starting_balance)

    limitations = list(LIMITATIONS)
    if weeks is None:
        limitations.append("Variable cash flow needs at least eight completed weeks with activity in at least half; only scheduled flows are available.")
    elif include_uncertainty and uncertainty is None:
        limitations.append("An illustrative range needs sixteen completed weeks, variable activity in at least eight, and variation in weekly net cash flow.")
    return {
        "as_of": as_of.isoformat(),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "horizon_days": horizon,
        "timezone": zone.key,
        "currency": currency,
        "starting_balance": money(starting_balance) if starting_balance is not None else None,
        "status": "estimated" if weeks is not None else "insufficient_history",
        "history": {
            "scan_start": history_start.isoformat(),
            "scan_end": as_of.isoformat(),
            "first_activity": first.isoformat() if first else None,
            "last_activity": last.isoformat() if last else None,
            "transaction_count": len(ledger),
            "active_days": len({item.day for item in ledger}),
            "recorded_income": money(previous["income"]),
            "recorded_gross_expenses": money(previous["expense"]),
            "recorded_refunds": money(previous["refund"]),
            "recorded_net_expenses": money(previous["expense"] - previous["refund"]),
            "baseline": coverage,
            "weeks": historical_weeks(ledger, as_of),
        },
        "recurring": events,
        "days": days,
        "totals": totals,
        "uncertainty": uncertainty,
        "scenario_options": {
            "weekly_variable_expenses_by_category": variable_category_rates(
                ledger, recurring_ids, as_of, coverage["complete_weeks"],
            ) if weeks is not None else {},
        },
        "assumptions": ASSUMPTIONS,
        "limitations": limitations,
    }
