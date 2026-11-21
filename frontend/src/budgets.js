export const budgetCategories = [
  "business services", "shopping", "entertainment", "groceries", "eating out",
  "bills", "transport", "health", "travel", "finance", "general",
];

const monthFormatter = new Intl.DateTimeFormat(undefined, {
  month: "long", year: "numeric", timeZone: "UTC",
});

export function monthLabel(period) {
  return monthFormatter.format(new Date(`${period.slice(0, 7)}-01T00:00:00Z`));
}

export function categoryLabel(category) {
  if (!category) return "Overall budget";
  return category.replace(/^./, (letter) => letter.toUpperCase());
}

export function currentMonth(date = new Date()) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

export function shiftMonth(period, offset) {
  const [year, month] = period.split("-").map(Number);
  const index = Math.min(9999 * 12 + 10, Math.max(12, year * 12 + month - 1 + offset));
  return `${String(Math.floor(index / 12)).padStart(4, "0")}-${String(index % 12 + 1).padStart(2, "0")}`;
}

function cents(value) {
  return Math.round(Number(value) * 100);
}

export function budgetTotals(records) {
  const active = records.filter((record) => !record.archived);
  const overall = new Set(active.filter((record) => record.category === null)
    .map((record) => record.currency));
  const totals = new Map();
  for (const record of active) {
    if (record.category !== null && overall.has(record.currency)) continue;
    const total = totals.get(record.currency) ?? { allocated: 0, spent: 0 };
    total.allocated += cents(record.amount);
    total.spent += cents(record.actual_spending);
    totals.set(record.currency, total);
  }
  return [...totals.entries()].sort(([a], [b]) => a.localeCompare(b))
    .map(([currency, { allocated, spent }]) => ({
      currency, allocated: allocated / 100, spent: spent / 100,
      remaining: (allocated - spent) / 100,
      utilization: allocated ? spent * 100 / allocated : 0,
      overall: overall.has(currency),
    }));
}

export function budgetStatus(budget) {
  const percent = Number(budget.percentage_used);
  const remaining = Number(budget.remaining);
  if (remaining < 0) return { tone: "over", label: "Over budget" };
  if (remaining === 0) return { tone: "near", label: "At limit" };
  if (percent >= 80) return { tone: "near", label: "Approaching limit" };
  return { tone: "safe", label: "Within budget" };
}

export function budgetError(error, fallback) {
  const data = error.response?.data;
  if (typeof data?.detail === "string") return data.detail;
  if (data && typeof data === "object") {
    const messages = Object.values(data).flat().filter((value) => typeof value === "string");
    if (messages.length) return messages.join(" ");
  }
  return fallback;
}

export function budgetPayload(draft) {
  const amount = draft.amount.trim().replace(",", ".");
  const currency = draft.currency.trim().toUpperCase();
  const period = draft.period.slice(0, 7);
  const raw = draft.thresholds.trim();
  const thresholds = raw ? raw.split(",").map((value) => value.trim()) : [];
  if (!/^\d{1,8}(?:\.\d{1,2})?$/.test(amount) || Number(amount) <= 0) {
    throw new Error("Enter a positive amount with up to two decimal places.");
  }
  if (!/^[A-Z]{3}$/.test(currency)) throw new Error("Enter a three-letter currency code.");
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(period) || period < "0001-01" || period > "9999-11"
      || ![period, `${period}-01`].includes(draft.period)) {
    throw new Error("Enter a valid month in YYYY-MM format.");
  }
  if ((draft.category && !budgetCategories.includes(draft.category))
      || thresholds.some((value) => !/^\d+$/.test(value) || Number(value) <= 0 || !Number.isSafeInteger(Number(value)))
      || new Set(thresholds.map(Number)).size !== thresholds.length) {
    throw new Error("Choose a valid category and enter distinct positive whole-number thresholds.");
  }
  return { category: draft.category || null, period, amount, currency, alert_thresholds: thresholds.map(Number) };
}

export function spendingHistory(periods, selectedPeriod, budget) {
  if (!budget) return [];
  const records = [];
  for (const { period, budgets } of periods) {
    if (period.slice(0, 7) > selectedPeriod) continue;
    const matches = budgets.filter((item) => item.category === budget.category && item.currency === budget.currency);
    const selected = matches.find((item) => !item.archived) ?? matches.at(-1);
    if (selected) records.push({
      period, month: monthLabel(period), allocated: Number(selected.amount),
      spent: Number(selected.actual_spending),
    });
  }
  return records.sort((a, b) => a.period.localeCompare(b.period)).slice(-12);
}


export function historicalBudgetTotals(records) {
  const current = budgetTotals(records);
  if (current.length) return current;
  // History groups are ordered by category and ID. Keep the latest archived
  // budget per category when the entire month has been archived.
  const latest = new Map(records.map((record) => [record.category, record]));
  return budgetTotals([...latest.values()].map((record) => ({ ...record, archived: false })));
}
