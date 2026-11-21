import assert from "node:assert/strict";
import test from "node:test";
import { blankGoal, formatGoalTotal, goalDraft, goalProgress, ledgerDraft, summarizeGoals } from "../src/financialGoals.js";

test("goal form validates target, date, currency, and monthly rate", () => {
  const invalid = goalDraft({
    ...blankGoal, name: "   ", target_amount: "0", currency: "€", target_date: "2027-02-29", monthly_contribution: "-5",
  });
  assert.deepEqual(Object.keys(invalid.errors), ["name", "target_amount", "currency", "target_date", "monthly_contribution"]);
  assert.deepEqual(goalDraft({
    ...blankGoal, name: " Trip ", target_amount: "50,5", currency: "eur", monthly_contribution: "0",
  }).payload, {
    name: "Trip", target_amount: "50.50", currency: "EUR", target_date: null, monthly_contribution: "0.00",
  });
});

test("ledger form prevents withdrawals beyond recorded savings", () => {
  const goal = { current_amount: "15.32", currency: "EUR" };
  const draft = { kind: "withdrawal", amount: "15.32", note: "  correction  " };
  assert.deepEqual(ledgerDraft(draft, goal).payload, { kind: "withdrawal", amount: "15.32", currency: "EUR", note: "correction" });
  assert.match(ledgerDraft({ ...draft, amount: "15.33" }, goal).error, /exceeds/);
  assert.match(ledgerDraft({ ...draft, amount: "15.001" }, goal).error, /two decimal places/);
  assert.match(ledgerDraft({ ...draft, amount: "0" }, goal).error, /positive/);
});

test("progress exposes actual funded percent while keeping the visual bar within its range", () => {
  assert.deepEqual(goalProgress({ progress_percent: "12.50" }), { width: 12.5, label: "12.5% funded" });
  assert.deepEqual(goalProgress({ progress_percent: "110.10" }), { width: 100, label: "110.1% funded" });
  assert.deepEqual(goalProgress({ progress_percent: "0.00" }), { width: 0, label: "0% funded" });
});

test("summary preserves exact decimal totals and keeps currencies and archived goals separate", () => {
  const totals = summarizeGoals([
    { currency: "USD", target_amount: "12.15", current_amount: "2.05" },
    { currency: "EUR", target_amount: "999999999999.99", current_amount: "0.10" },
    { currency: "EUR", target_amount: "0.01", current_amount: "0.20" },
    { currency: "USD", target_amount: "900.00", current_amount: "350.00", archived: true },
  ]);
  assert.deepEqual(totals, [
    { currency: "EUR", target: 100000000000000n, saved: 30n },
    { currency: "USD", target: 1215n, saved: 205n },
  ]);
  assert.match(formatGoalTotal(totals[0].saved, "EUR"), /(?:0[.,]30|٠[٫]٣٠)/);
});
