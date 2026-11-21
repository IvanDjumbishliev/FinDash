export const horizons = [30, 60, 90];

export function balanceInput(value) {
  const normalized = value.trim().replace(",", ".");
  if (!normalized) return { value: "" };
  if (!/^-?\d{1,12}(?:\.\d{1,2})?$/.test(normalized)) {
    return { error: "Enter a balance with up to two decimal places, such as 1250.50 or -25." };
  }
  return { value: normalized };
}

function cents(value) {
  return value == null ? null : Math.round(Number(value) * 100);
}

export function forecastMetrics(data) {
  const { totals } = data;
  const full = data.status === "estimated";
  const combined = (scheduled, variable) => (cents(scheduled) + (full ? cents(variable) : 0)) / 100;
  const balance = full ? totals.estimated_ending_balance : totals.scheduled_only_ending_balance;
  return [
    { label: full ? "Expected income" : "Scheduled income",
      value: combined(totals.scheduled_income, totals.estimated_variable_income),
      detail: full ? "Scheduled + variable estimate" : "Known recurring flows" },
    { label: full ? "Expected net expenses" : "Scheduled expenses",
      value: combined(totals.scheduled_expenses, totals.estimated_variable_expenses),
      detail: full ? "Includes estimated refunds" : "Known recurring flows" },
    { label: full ? "Projected net cash flow" : "Scheduled net cash flow",
      value: full ? totals.estimated_net_cash_flow : totals.scheduled_net_cash_flow,
      detail: `Over ${data.horizon_days} days` },
    { label: full ? "Estimated ending balance" : "Scheduled-only ending balance", value: balance,
      detail: balance == null ? "Enter a starting balance" : data.end_date },
  ];
}

export function weeklyCashFlow(data) {
  const actual = (data.history.weeks ?? []).map((week) => ({
    start: week.start_date, end: week.end_date, value: Number(week.net_cash_flow),
    count: week.transaction_count,
  }));
  const projected = [];
  const full = data.status === "estimated";
  for (let index = 0; index < data.days.length; index += 7) {
    const group = data.days.slice(index, index + 7);
    const total = group.reduce((sum, day) => sum + (full ? cents(day.estimated_net_cash_flow)
      : cents(day.scheduled_income) - cents(day.scheduled_expenses)), 0);
    projected.push({ start: group[0].date, end: group.at(-1).date, value: total / 100 });
  }
  return { actual, projected };
}

export function trajectory(data) {
  const hasBalance = data.starting_balance != null;
  const full = data.status === "estimated";
  const byDate = new Map((data.uncertainty?.days ?? []).map((day) => [day.date, day]));
  let cumulative = hasBalance ? cents(data.starting_balance) : 0;
  return [
    { date: data.as_of, value: cumulative / 100 },
    ...data.days.map((day) => {
      cumulative += full ? cents(day.estimated_net_cash_flow) : cents(day.scheduled_income) - cents(day.scheduled_expenses);
      const band = byDate.get(day.date)?.[hasBalance ? "ending_balance" : "net_cash_flow"];
      return {
        date: day.date,
        value: hasBalance && full ? Number(day.estimated_balance) : cumulative / 100,
        ...(band ? { band: [Number(band.lower), Number(band.upper)] } : {}),
      };
    }),
  ];
}

export function recurringPayments(streams) {
  return streams.flatMap(({ dates, ...stream }, index) => dates.map((date) => ({
    ...stream, date, key: `${index}-${date}`,
  }))).sort((a, b) => a.date.localeCompare(b.date) || a.label.localeCompare(b.label));
}
