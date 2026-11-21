from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from api.services.goals import ZERO, project_goal
from api.services.subscriptions import shifted_date

CHART_MAX_MONTHS = 60


@dataclass(frozen=True)
class ScenarioGoal:
    currency: str
    target_amount: Decimal
    target_date: date | None
    current_amount: Decimal


def completion(goal, today, monthly):
    result = project_goal(goal, today, monthly)
    if result["status"] == "completed":
        result["projected_completion_date"] = today
        result["projected_on_time"] = today <= goal.target_date if goal.target_date else None
    return {
        **result,
        "target_amount": format(goal.target_amount, ".2f"),
        "starting_amount": format(goal.current_amount, ".2f"),
        "remaining_amount": format(result["remaining_amount"], ".2f"),
        "monthly_contribution": format(monthly, ".2f"),
    }


def funded_percent(goal, monthly, months):
    saved = goal.current_amount + monthly * months
    return format(min(Decimal(100), saved * 100 / goal.target_amount), ".2f")


def compare_goal_scenario(goal, today, changes):
    baseline_goal = ScenarioGoal(goal.currency, goal.target_amount, goal.target_date, goal.current_amount)
    monthly = goal.monthly_contribution or ZERO
    scenario_monthly = changes.get("monthly_contribution", monthly) + changes.get("expense_reduction", ZERO)
    scenario_goal = replace(
        baseline_goal,
        target_amount=changes.get("target_amount", baseline_goal.target_amount),
        target_date=changes.get("target_date", baseline_goal.target_date),
        current_amount=baseline_goal.current_amount + changes.get("one_time_contribution", ZERO),
    )
    baseline = completion(baseline_goal, today, monthly)
    scenario = completion(scenario_goal, today, scenario_monthly)
    baseline_months = baseline["months_remaining"]
    scenario_months = scenario["months_remaining"]
    months_saved = (
        baseline_months - scenario_months if baseline_months is not None and scenario_months is not None else None
    )
    desired = max(12, baseline_months or 0, scenario_months or 0)
    months = min(desired, CHART_MAX_MONTHS, (date.max.year - today.year) * 12 + date.max.month - today.month)
    points = [{
        "date": shifted_date(today, index, today.day).isoformat(),
        "baseline": funded_percent(baseline_goal, monthly, index),
        "scenario": funded_percent(scenario_goal, scenario_monthly, index),
    } for index in range(months + 1)]
    return {
        "currency": goal.currency,
        "baseline": baseline,
        "scenario": scenario,
        "months_saved": months_saved,
        "chart": {"points": points, "truncated": months < desired},
        "assumptions": [
            "The starting balance is the amount recorded for this goal. A one-time contribution is applied immediately.",
            "Monthly contributions begin one month from today. The entire monthly expense reduction is diverted to savings.",
            "The chart shows the percentage of each plan’s own target, capped at 100%.",
            "Estimates assume steady contributions and exclude interest, fees, withdrawals, and changes in expenses.",
        ],
    }
