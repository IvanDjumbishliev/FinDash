import { displayDate } from "./copilotPresentation.js";

export const goalsEndpoint = "/api/goals/";
export const goalEndpoint = (id) => `${goalsEndpoint}${id}/`;
export const blankGoal = { name: "", target_amount: "", currency: "EUR", target_date: "", monthly_contribution: "" };

export function cents(value) {
  const match = /^(\d{1,12})(?:[.,](\d{1,2}))?$/.exec(value.trim());
  return match ? BigInt(match[1]) * 100n + BigInt((match[2] || "").padEnd(2, "0")) : null;
}

function decimal(value) {
  return `${value / 100n}.${String(value % 100n).padStart(2, "0")}`;
}

export function goalDraft(draft) {
  const name = draft.name.trim();
  const target = cents(draft.target_amount);
  const currency = draft.currency.trim().toUpperCase();
  const rate = draft.monthly_contribution.trim() ? cents(draft.monthly_contribution) : null;
  const errors = {};
  if (!name) errors.name = "Enter a goal name.";
  if (target === null || target === 0n) errors.target_amount = "Enter a positive amount with up to two decimal places.";
  if (!/^[A-Z]{3}$/.test(currency)) errors.currency = "Enter a three-letter currency code.";
  if (draft.target_date && !displayDate(draft.target_date)) errors.target_date = "Enter a valid target date.";
  if (draft.monthly_contribution.trim() && rate === null) {
    errors.monthly_contribution = "Enter a positive amount, zero, or leave it blank.";
  }
  if (Object.keys(errors).length) return { errors };
  return { errors, payload: {
    name, target_amount: decimal(target), currency, target_date: draft.target_date || null,
    monthly_contribution: rate === null ? null : decimal(rate),
  } };
}

export function ledgerDraft(draft, goal) {
  const amount = cents(draft.amount);
  if (amount === null || amount === 0n) return { error: "Enter a positive amount with up to two decimal places." };
  if (draft.kind === "withdrawal" && amount > cents(goal.current_amount)) {
    return { error: "The withdrawal exceeds the amount recorded for this goal." };
  }
  return { payload: { kind: draft.kind, amount: decimal(amount), currency: goal.currency, note: draft.note.trim() } };
}

export function summarizeGoals(goals) {
  const totals = new Map();
  for (const goal of goals) {
    if (goal.archived) continue;
    const row = totals.get(goal.currency) || { currency: goal.currency, target: 0n, saved: 0n };
    row.target += cents(goal.target_amount);
    row.saved += cents(goal.current_amount);
    totals.set(goal.currency, row);
  }
  return [...totals.values()].sort((a, b) => a.currency.localeCompare(b.currency));
}

export function formatGoalTotal(value, currency) {
  const parts = new Intl.NumberFormat(undefined, {
    style: "currency", currency, currencyDisplay: "code", minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).formatToParts(value / 100n);
  const fraction = new Intl.NumberFormat(undefined, { minimumIntegerDigits: 2, useGrouping: false }).format(value % 100n);
  return parts.map((part) => part.type === "fraction" ? fraction : part.value).join("");
}

export function goalProgress(goal) {
  const percent = Number(goal.progress_percent);
  return { width: Math.min(100, Math.max(0, percent)), label: `${percent}% funded` };
}

export function goalError(error, fallback) {
  const data = error.response?.data;
  if (typeof data?.detail === "string") return data.detail;
  const field = Object.values(data || {}).find((value) => typeof value?.[0] === "string" && Array.isArray(value));
  return field?.[0] || fallback;
}
