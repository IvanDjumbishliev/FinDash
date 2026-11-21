from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from api.services.budgets import ZERO
from api.services.copilot_tools import money
from api.services.forecast_recurrence import Schedule
from api.services.forecasting import cents


def scenario_adjustments(baseline, changes):
    by_day = defaultdict(lambda: {"income": ZERO, "expenses": ZERO})
    notes = []
    start = date.fromisoformat(baseline["start_date"])
    end = date.fromisoformat(baseline["end_date"])
    for key, kind, label in (
        ("monthly_income", "income", "The monthly income increase"),
        ("recurring_expense", "expenses", "The new recurring expense"),
        ("purchase", "expenses", "The one-time purchase"),
    ):
        rule = changes.get(key)
        if not rule:
            continue
        first = start + timedelta(days=rule["day"] - 1)
        if first > end:
            notes.append(f"{label} is outside this forecast horizon.")
            continue
        if key == "purchase":
            dates = [first]
        else:
            schedule = Schedule(
                label="", identity="", kind=kind, amount=Decimal(rule["amount"]),
                frequency=rule.get("frequency", "monthly"), anchor=first.day, first=first,
                source="hypothetical",
            )
            dates = schedule.dates(start, end)
        for due in dates:
            by_day[due.isoformat()][kind] += Decimal(rule["amount"])

    remove_id = changes.get("remove_subscription_id")
    if remove_id is not None:
        subscription = next((
            entry for entry in baseline["recurring"]
            if entry.get("subscription_id") == remove_id and entry["source"] == "confirmed_subscription"
        ), None)
        if subscription is None:
            notes.append("The selected subscription has no eligible charge in this forecast horizon.")
        else:
            for due in subscription["dates"]:
                by_day[due]["expenses"] -= Decimal(subscription["amount"])
    return by_day, notes


def compare_scenario(baseline, changes):
    """Project hypothetical deltas from an already calculated read-only forecast."""
    adjustments, notes = scenario_adjustments(baseline, changes)
    weekly_cut = ZERO
    reduction = changes.get("spending_reduction")
    if reduction:
        categories = baseline["scenario_options"]["weekly_variable_expenses_by_category"]
        rate = categories.get(reduction["category"])
        if rate is None:
            notes.append("Recorded variable spending is insufficient to estimate the selected category reduction.")
        else:
            weekly_cut = Decimal(rate) * Decimal(reduction["percent"]) / 100

    full = baseline["status"] == "estimated"
    base_balance = None if baseline["starting_balance"] is None else Decimal(baseline["starting_balance"])
    scenario_balance = Decimal(changes["starting_balance"]) if "starting_balance" in changes else base_balance
    base_flow = scenario_flow = previous_cut = ZERO
    days = []

    def point(day):
        return {
            "date": day,
            "baseline_net_cash_flow": money(base_flow),
            "scenario_net_cash_flow": money(scenario_flow),
            "baseline_balance": money(base_balance + base_flow) if base_balance is not None else None,
            "scenario_balance": money(scenario_balance + scenario_flow) if scenario_balance is not None else None,
            "balance_difference": money(scenario_balance + scenario_flow - base_balance - base_flow)
            if base_balance is not None and scenario_balance is not None else None,
            "net_cash_flow_difference": money(scenario_flow - base_flow),
        }

    days.append(point(baseline["as_of"]))
    for offset, day in enumerate(baseline["days"], 1):
        if full:
            daily_net = Decimal(day["estimated_net_cash_flow"])
            variable_expenses = max(ZERO, Decimal(day["estimated_variable_expenses"]))
        else:
            daily_net = Decimal(day["scheduled_income"]) - Decimal(day["scheduled_expenses"])
            variable_expenses = ZERO
        cumulative_cut = cents(weekly_cut * offset / 7)
        cut = min(cumulative_cut - previous_cut, variable_expenses)
        previous_cut = cumulative_cut
        delta = adjustments[day["date"]]
        base_flow += daily_net
        scenario_flow += daily_net + delta["income"] - delta["expenses"] + cut
        days.append(point(day["date"]))

    return {
        "days": days, "totals": days[-1], "notes": notes,
        "currency": baseline["currency"], "horizon_days": baseline["horizon_days"],
        "status": baseline["status"], "hypothetical": True,
    }
