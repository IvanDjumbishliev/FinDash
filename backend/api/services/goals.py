from datetime import date
from decimal import ROUND_CEILING, Decimal

from api.models import GoalContribution
from api.services.subscriptions import shifted_date

ZERO = Decimal("0.00")
MAX_BALANCE = Decimal("999999999999.99")


class GoalLedgerError(ValueError):
    pass


def remaining_amount(goal):
    return max(ZERO, goal.target_amount - goal.current_amount)


def record_entry(goal, *, kind, amount, note="", request_id=None):
    """Append an entry inside the caller's transaction with the goal write-locked."""
    if request_id is not None:
        previous = goal.contributions.filter(request_id=request_id).first()
        if previous:
            if (previous.kind, previous.amount, previous.note) != (kind, amount, note):
                raise GoalLedgerError("This request ID was already used for a different entry.")
            return previous, False

    if goal.archived:
        raise GoalLedgerError("Restore the goal before recording a contribution or withdrawal.")

    change = -amount if kind == GoalContribution.Kind.WITHDRAWAL else amount
    balance = goal.current_amount + change
    if balance < ZERO:
        raise GoalLedgerError("Withdrawal exceeds the current goal balance.")
    if balance > MAX_BALANCE:
        raise GoalLedgerError("Contribution exceeds the maximum goal balance.")

    entry = goal.contributions.create(
        kind=kind, amount=amount, balance_after=balance, note=note, request_id=request_id,
    )
    goal.current_amount = balance
    goal.save(update_fields=["current_amount", "updated_at"])
    return entry, True


def project_goal(goal, today, monthly_contribution):
    remaining = remaining_amount(goal)
    months = None
    completion = None
    on_time = None
    if remaining == ZERO:
        status = "completed"
        months = 0
    elif not monthly_contribution:
        status = "no_contribution_rate"
    else:
        months = int((remaining / monthly_contribution).to_integral_value(rounding=ROUND_CEILING))
        if months > (date.max.year - today.year) * 12 + date.max.month - today.month:
            status = "date_out_of_range"
        else:
            status = "estimated"
            completion = shifted_date(today, months, today.day)
        if goal.target_date:
            on_time = completion is not None and completion <= goal.target_date

    return {
        "as_of": today,
        "currency": goal.currency,
        "target_date": goal.target_date,
        "remaining_amount": remaining,
        "monthly_contribution": monthly_contribution,
        "months_remaining": months,
        "projected_completion_date": completion,
        "projected_on_time": on_time,
        "status": status,
    }
