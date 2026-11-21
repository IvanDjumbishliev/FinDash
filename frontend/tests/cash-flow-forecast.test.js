import assert from "node:assert/strict";
import test from "node:test";
import { balanceInput, forecastMetrics, recurringPayments, trajectory, weeklyCashFlow } from "../src/cashFlowForecast.js";

const fixture = {
  status: "estimated", horizon_days: 30, as_of: "2026-04-30",
  start_date: "2026-05-01", end_date: "2026-05-30", starting_balance: "-5.00",
  history: { weeks: [{ start_date: "2026-04-24", end_date: "2026-04-30", net_cash_flow: "-3.25", transaction_count: 2 }] },
  days: [
    { date: "2026-05-01", scheduled_income: "0.00", scheduled_expenses: "4.50", estimated_net_cash_flow: "-3.20", estimated_balance: "-8.20" },
    { date: "2026-05-02", scheduled_income: "10.00", scheduled_expenses: "0.00", estimated_net_cash_flow: "9.10", estimated_balance: "0.90" },
  ],
  totals: { scheduled_income: "10.00", scheduled_expenses: "4.50", scheduled_net_cash_flow: "5.50",
    estimated_variable_income: "3.20", estimated_variable_expenses: "2.80", estimated_net_cash_flow: "5.90",
    scheduled_only_ending_balance: "0.50", estimated_ending_balance: "0.90" },
  uncertainty: { days: [
    { date: "2026-05-01", net_cash_flow: { lower: "-4.30", upper: "-2.90" },
      ending_balance: { lower: "-9.30", upper: "-7.90" } },
  ] },
};

test("starting balance accepts signed amounts and refuses malformed currency text", () => {
  assert.deepEqual(balanceInput(""), { value: "" });
  assert.deepEqual(balanceInput("  -1200,05 "), { value: "-1200.05" });
  for (const input of ["1.002", "USD 200", "NaN", "1234567890123", "1e3", "1,222.25"]) {
    assert.ok(balanceInput(input).error, input);
  }
});

test("segments weekly cash flow at the forecast boundary and uses scheduled flow only for sparse history", () => {
  assert.deepEqual(weeklyCashFlow(fixture), {
    actual: [{ start: "2026-04-24", end: "2026-04-30", value: -3.25, count: 2 }],
    projected: [{ start: "2026-05-01", end: "2026-05-02", value: 5.9 }],
  });
  const sparse = { ...fixture, status: "insufficient_history" };
  assert.equal(weeklyCashFlow(sparse).projected[0].value, 5.5);
  assert.deepEqual(forecastMetrics(sparse).map((metric) => metric.value), [10, 4.5, "5.50", "0.50"]);
  assert.deepEqual(forecastMetrics(fixture).map((metric) => metric.value), [13.2, 7.3, "5.90", "0.90"]);
});

test("trajectory shows only server-supplied bounds and distinguishes balance from cumulative change", () => {
  assert.deepEqual(trajectory(fixture), [
    { date: "2026-04-30", value: -5 },
    { date: "2026-05-01", value: -8.2, band: [-9.3, -7.9] },
    { date: "2026-05-02", value: 0.9 },
  ]);
  assert.deepEqual(trajectory({ ...fixture, starting_balance: null, uncertainty: null }), [
    { date: "2026-04-30", value: 0 }, { date: "2026-05-01", value: -3.2 }, { date: "2026-05-02", value: 5.9 },
  ]);
});

test("recurring entries are displayed in chronological order", () => {
  const entries = recurringPayments([
    { label: "Payroll", kind: "income", dates: ["2026-05-04", "2026-05-18"] },
    { label: "Utilities", kind: "expense", dates: ["2026-05-02"] },
  ]);
  assert.deepEqual(entries.map(({ label, date }) => [label, date]), [
    ["Utilities", "2026-05-02"], ["Payroll", "2026-05-04"], ["Payroll", "2026-05-18"],
  ]);
});
