import assert from "node:assert/strict";
import { Buffer } from "node:buffer";
import { test } from "node:test";
import { build } from "esbuild";
import { renderToStaticMarkup } from "react-dom/server";
import {
  budgetPayload, budgetStatus, budgetTotals, historicalBudgetTotals, spendingHistory, shiftMonth,
} from "../src/budgets.js";

const record = (attributes = {}) => ({
  id: 1, category: "groceries", amount: "100.00", currency: "EUR",
  actual_spending: "75.00", remaining: "25.00", percentage_used: "75.00",
  archived: false, period: "2026-11-01", ...attributes,
});

test("overview uses an overall budget without double counting and separates currencies", () => {
  assert.deepEqual(budgetTotals([
    record(),
    record({ category: null, amount: "200", actual_spending: "190" }),
    record({ currency: "USD", amount: "40", actual_spending: "50" }),
    record({ category: "bills", currency: "USD", archived: true }),
  ]), [
    { currency: "EUR", allocated: 200, spent: 190, remaining: 10, utilization: 95, overall: true },
    { currency: "USD", allocated: 40, spent: 50, remaining: -10, utilization: 125, overall: false },
  ]);
});

test("progress states identify approaching, exact limit, and overspending", () => {
  assert.equal(budgetStatus(record()).label, "Within budget");
  assert.equal(budgetStatus(record({ percentage_used: "80", remaining: "20" })).label, "Approaching limit");
  assert.equal(budgetStatus(record({ percentage_used: "100", remaining: "0" })).label, "At limit");
  assert.equal(budgetStatus(record({ percentage_used: "100.00", remaining: "-0.01" })).label, "Over budget");
});

test("history compares like categories and currencies and retains archived months", () => {
  const periods = [
    { period: "2026-11-01", budgets: [record(), record({ archived: true, actual_spending: "999" })] },
    { period: "2026-10-01", budgets: [record({ currency: "USD" })] },
    { period: "2026-09-01", budgets: [record({ archived: true, actual_spending: "10" })] },
    { period: "2026-12-01", budgets: [record()] },
  ];
  assert.deepEqual(
    spendingHistory(periods, "2026-11", record()).map(({ period, spent }) => [period, spent]),
    [["2026-09-01", 10], ["2026-11-01", 75]]
  );
  assert.equal(historicalBudgetTotals(periods[2].budgets)[0].spent, 10);
  assert.equal(shiftMonth("2026-12", 1), "2027-01");
});

test("editor converts valid input and rejects negative amounts and duplicate thresholds", () => {
  const draft = { category: "", period: "2026-11", amount: "20,25", currency: "eur", thresholds: "50, 80" };
  assert.deepEqual(budgetPayload(draft), {
    category: null, period: "2026-11", amount: "20.25", currency: "EUR", alert_thresholds: [50, 80],
  });
  assert.throws(() => budgetPayload({ ...draft, thresholds: "50, 050" }));
  assert.throws(() => budgetPayload({ ...draft, amount: "-1" }));
});

test("budget card communicates overspending and delegates the two actions to the supplied budget", async () => {
  // Vite already ships esbuild. Compile the JSX for the existing Node test runner.
  const bundle = await build({
    entryPoints: [new URL("../src/components/BudgetCard.jsx", import.meta.url).pathname],
    bundle: true, write: false, format: "esm", jsx: "automatic",
    define: { "process.env.NODE_ENV": '"production"' },
  });
  const module = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString("base64")}`);
  const budget = record({ percentage_used: "120", remaining: "-20", actual_spending: "120" });
  const calls = [];
  const card = module.default({
    budget, selected: true,
    onView: (value) => calls.push(["view", value]),
    onEdit: (value) => calls.push(["edit", value]),
  });

  const markup = renderToStaticMarkup(card);
  assert.match(markup, /120% used\. Over budget\./);
  assert.match(markup, /aria-valuenow="100"/);
  assert.match(markup, /aria-pressed="true"/);
  const actions = card.props.children.at(-1).props.children;
  actions.forEach((button) => button.props.onClick());
  assert.deepEqual(calls, [["view", budget], ["edit", budget]]);
});
