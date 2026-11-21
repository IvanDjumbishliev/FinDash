import PropTypes from "prop-types";
import { budgetStatus, categoryLabel } from "../budgets.js";
import { formatMoney } from "../subscriptions.js";

export default function BudgetCard({ budget, onView, onEdit, selected = false }) {
  const { tone, label } = budgetStatus(budget);
  const used = Number(budget.percentage_used);
  const percent = Math.max(0, Math.min(used, 100));
  const format = (amount) => formatMoney(amount, budget.currency);

  return (
    <article className="budget-panel budget-card" data-tone={tone} data-selected={selected}>
      <div className="budget-card-heading">
        <h3>{categoryLabel(budget.category)}</h3>
        <span className="budget-state">{label}</span>
      </div>
      <p className="budget-card-amount"><strong>{format(budget.actual_spending)}</strong> <span>of {format(budget.amount)}</span></p>
      <div className="budget-progress"
        role="progressbar" aria-label={`${categoryLabel(budget.category)} utilization`}
        aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-valuetext={`${used}% used. ${label}.`}>
        <span key={percent} style={{ width: `${percent}%` }} />
      </div>
      <div className="budget-card-detail">
        <span>{used}% used</span>
        <span>{format(Math.abs(Number(budget.remaining)))} {Number(budget.remaining) < 0 ? "over" : "remaining"}</span>
      </div>
      {budget.reached_thresholds?.length > 0 && (
        <p className="budget-muted">Thresholds reached {budget.reached_thresholds.map((value) => `${value}%`).join(", ")}</p>
      )}
      <div className="budget-actions">
        <button type="button" onClick={() => onView(budget)} aria-pressed={selected}>View spending</button>
        <button type="button" onClick={() => onEdit(budget)} aria-label={`Edit ${categoryLabel(budget.category)}`}>Edit</button>
      </div>
    </article>
  );
}

BudgetCard.propTypes = {
  budget: PropTypes.shape({
    category: PropTypes.string,
    currency: PropTypes.string.isRequired,
    amount: PropTypes.string.isRequired,
    actual_spending: PropTypes.string.isRequired,
    remaining: PropTypes.string.isRequired,
    percentage_used: PropTypes.string.isRequired,
    reached_thresholds: PropTypes.arrayOf(PropTypes.number),
  }).isRequired,
  onView: PropTypes.func.isRequired,
  onEdit: PropTypes.func.isRequired,
  selected: PropTypes.bool,
};
