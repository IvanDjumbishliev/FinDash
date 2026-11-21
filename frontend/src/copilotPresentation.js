const dayFormat = new Intl.DateTimeFormat(undefined, {
  month: "short", day: "numeric", year: "numeric", timeZone: "UTC",
});

export function displayDate(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return "";
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(date.valueOf()) || date.toISOString().slice(0, 10) !== value ? "" : dayFormat.format(date);
}

export function displayRange(start, end) {
  const a = displayDate(start);
  const b = displayDate(end);
  return a && b ? (start === end ? a : `${a} – ${b}`) : "";
}

function amount(value) {
  if (typeof value === "string" && /^-?\d+(\.\d+)?$/.test(value)) value = Number(value);
  return Number.isFinite(value) ? value : null;
}

function validCurrency(currency) {
  return typeof currency === "string" && /^[A-Z]{3}$/.test(currency);
}

export function money(value, currency) {
  const number = amount(value);
  if (number === null || !validCurrency(currency)) return "—";
  return new Intl.NumberFormat(undefined, {
    style: "currency", currency, currencyDisplay: "code",
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(number);
}

export function chartModel(response) {
  const spec = response.visualization;
  if (!Number.isInteger(spec?.metric_index) || spec.metric_index < 0) return null;
  const metric = response.metrics?.[spec.metric_index];
  const totals = Array.isArray(metric?.totals) ? metric.totals : [];
  const series = [];
  for (const total of totals) {
    if (!validCurrency(total.currency)) continue;
    let rows = [];
    if (spec.type === "category_breakdown" && metric.tool === "get_category_breakdown") {
      rows = Object.entries(total.categories ?? {}).flatMap(([label, value]) => {
        const numeric = amount(value);
        return numeric === null ? [] : [{ label, value: numeric }];
      }).sort((a, b) => b.value - a.value);
    } else if (spec.type === "period_comparison" && metric.tool === "compare_spending_periods") {
      const ranges = [metric.period_a, metric.period_b];
      rows = [total.period_a_net_spending, total.period_b_net_spending].flatMap((value, index) => {
        const numeric = amount(value);
        if (numeric === null) return [];
        const label = index === 0 ? "Period A" : "Period B";
        return [{ label, value: numeric, detail: displayRange(...(ranges[index] ?? [])) }];
      });
      if (rows.length !== 2) continue;
    }
    if (rows.length) series.push({ currency: total.currency, rows });
  }
  if (!series.length) return null;
  return {
    type: spec.type,
    title: spec.type === "period_comparison" ? "Spending by period" : "Spending by category",
    series,
  };
}

export function metricCards(metrics = []) {
  return metrics.flatMap((metric) => {
    switch (metric.tool) {
      case "get_spending_summary":
      case "get_category_breakdown":
        return (metric.totals ?? []).filter((row) => row.transaction_count > 0).map((row) => ({
          label: metric.category ? `Net spending · ${metric.category}` : "Net spending",
          value: money(row.net_spending, row.currency),
          detail: `${row.transaction_count} recorded ${row.transaction_count === 1 ? "entry" : "entries"}`,
        }));
      case "compare_spending_periods":
        return (metric.totals ?? []).filter((row) => amount(row.change_b_minus_a) !== null).map((row) => ({
          label: "Change in net spending",
          value: money(row.change_b_minus_a, row.currency),
          detail: `${money(row.period_a_net_spending, row.currency)} → ${money(row.period_b_net_spending, row.currency)}`,
        }));
      case "get_budget_status":
        return (metric.budgets ?? []).map((row) => ({
          label: row.category || "Overall budget",
          value: `${row.percentage_used}% used`,
          detail: `${money(row.actual_spending, row.currency)} of ${money(row.limit, row.currency)}`,
        }));
      case "get_subscription_summary":
        return (metric.totals ?? []).map((row) => ({
          label: "Estimated monthly subscriptions",
          value: money(row.estimated_monthly, row.currency),
          detail: `${money(row.estimated_annual, row.currency)} estimated annually`,
        }));
      case "get_recent_transactions":
        return metric.transactions?.length ? [{
          label: "Recent transactions", value: String(metric.transactions.length), detail: "Entries returned",
        }] : [];
      default:
        return [];
    }
  });
}

export const suggestedQuestions = [
  { title: "Understand spending", prompt: "How much did I spend on groceries last month?", icon: "spending" },
  { title: "Compare periods", prompt: "Compare my spending in September and October.", icon: "compare" },
  { title: "Check my budgets", prompt: "Which budget categories are close to their limits?", icon: "budgets" },
  { title: "Review subscriptions", prompt: "What are my biggest recurring expenses?", icon: "subscriptions" },
];

export function followUpQuestions(response) {
  const tools = new Set(response.metrics?.map((metric) => metric.tool));
  const ranges = response.date_ranges ?? [];
  const period = ranges[0];
  const later = ranges.at(-1);
  if (tools.has("compare_spending_periods") && period && later && ranges.length > 1) {
    return [
      `Which category increased the most between ${period.start_date} and ${later.start_date}?`,
      `Break down my spending from ${later.start_date} through ${later.end_date} by category.`,
    ];
  }
  if (period && (tools.has("get_spending_summary") || tools.has("get_category_breakdown"))) {
    return [
      `How did spending from ${period.start_date} through ${period.end_date} compare with the preceding period?`,
      "Which budget categories are closest to their limits?",
    ];
  }
  if (tools.has("get_budget_status") || tools.has("get_subscription_summary")) {
    return ["Summarize my spending this month.", "How does my spending this month compare with last month?"];
  }
  return ["Summarize my spending this month.", "What are my biggest recurring expenses?"];
}
