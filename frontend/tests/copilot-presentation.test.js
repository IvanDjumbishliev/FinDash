import assert from "node:assert/strict";
import test from "node:test";
import { chartModel, displayDate, displayRange, followUpQuestions, metricCards } from "../src/copilotPresentation.js";

test("category chart keeps currencies separate and preserves refund values and zero", () => {
  const response = {
    visualization: { type: "category_breakdown", metric_index: 1 },
    metrics: [{ tool: "get_budget_status" }, { tool: "get_category_breakdown", totals: [
      { currency: "USD", categories: { groceries: "12.50", shopping: "-4.20", bills: "0", invalid: null } },
      { currency: "EUR", categories: { groceries: "19.00" } },
    ] }],
  };
  assert.deepEqual(chartModel(response).series, [
    { currency: "USD", rows: [{ label: "groceries", value: 12.5 }, { label: "bills", value: 0 }, { label: "shopping", value: -4.2 }] },
    { currency: "EUR", rows: [{ label: "groceries", value: 19 }] },
  ]);
  assert.equal(chartModel({ ...response, visualization: { ...response.visualization, metric_index: 0 } }), null);
  assert.equal(chartModel({ ...response, visualization: { ...response.visualization, type: "custom" } }), null);
});

test("comparison skips currency pairs with missing observations and retains date labels", () => {
  const metric = {
    tool: "compare_spending_periods", period_a: ["2026-03-01", "2026-03-31"], period_b: ["2026-04-01", "2026-04-30"],
    totals: [
      { currency: "USD", period_a_net_spending: "0", period_b_net_spending: "-5", change_b_minus_a: "-5" },
      { currency: "EUR", period_a_net_spending: null, period_b_net_spending: "17", change_b_minus_a: null },
    ],
  };
  const visualization = { type: "period_comparison", metric_index: 0 };
  const response = { visualization, metrics: [metric], date_ranges: [
    { start_date: metric.period_a[0], end_date: metric.period_a[1] },
    { start_date: metric.period_b[0], end_date: metric.period_b[1] },
  ] };
  assert.deepEqual(chartModel(response).series, [{ currency: "USD", rows: [
    { label: "Period A", detail: displayRange(...metric.period_a), value: 0 },
    { label: "Period B", detail: displayRange(...metric.period_b), value: -5 },
  ] }]);
  assert.equal(metricCards(response.metrics).length, 1);
  assert.match(followUpQuestions(response)[0], /2026-03-01.*2026-04-01/);
});

test("cards distinguish estimates, skip empty categories and preserve calendar dates", () => {
  const metrics = [
    { tool: "get_category_breakdown", category: "groceries", totals: [{ currency: "USD", net_spending: "0", transaction_count: 0 }] },
    { tool: "get_subscription_summary", totals: [{ currency: "EUR", estimated_monthly: "9", estimated_annual: "108" }] },
    { tool: "get_budget_status", budgets: [{ currency: "USD", percentage_used: "85.00", actual_spending: "85", limit: "100" }] },
  ];
  const cards = metricCards(metrics);
  assert.equal(cards.length, 2);
  assert.match(cards[0].label, /Estimated/);
  assert.equal(cards[1].value, "85.00% used");
  assert.equal(displayDate("2026-02-30"), "");
  assert.equal(displayRange("2026-04-01", "2026-04-01"), displayDate("2026-04-01"));
});
