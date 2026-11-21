import { displayDate } from "./copilotPresentation.js";
import { cents, decimal } from "./financialGoals.js";

export const blankScenario = {
  monthly_contribution: "", one_time_contribution: "", expense_reduction: "", target_amount: "", target_date: "",
  dateMode: "saved",
};

const labels = {
  monthly_contribution: "Monthly contribution",
  one_time_contribution: "One-time contribution",
  expense_reduction: "Monthly expense reduction",
  target_amount: "Target amount",
};

export function scenarioChanges(draft) {
  const changes = {};
  const errors = {};
  for (const [field, label] of Object.entries(labels)) {
    const value = draft[field].trim();
    if (!value) continue;
    const amount = cents(value);
    if (amount === null || (field === "target_amount" && amount === 0n)) {
      errors[field] = field === "target_amount" ? "Enter a positive target with up to two decimal places." :
        `${label} must be zero or more with up to two decimal places.`;
    } else {
      changes[field] = decimal(amount);
    }
  }
  if (draft.dateMode === "clear") changes.target_date = null;
  if (draft.dateMode === "custom") {
    if (displayDate(draft.target_date)) changes.target_date = draft.target_date;
    else errors.target_date = "Enter a valid target date.";
  }
  return { changes, errors };
}

export function scenarioDraft(changes) {
  return {
    ...blankScenario,
    ...changes,
    target_date: changes.target_date || "",
    dateMode: changes.target_date ? "custom" : changes.target_date === null ? "clear" : "saved",
  };
}

export function sliderScale(value, reference) {
  const minimum = 0;
  const ceiling = Math.max(100, reference * 2, value);
  const step = Math.max(1, 10 ** Math.floor(Math.log10(ceiling / 100)));
  return { min: minimum, max: Math.min(999999999999, Math.ceil(ceiling / step) * step), step, value };
}
