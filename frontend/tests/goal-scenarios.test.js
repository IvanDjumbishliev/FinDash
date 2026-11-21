import assert from "node:assert/strict";
import test from "node:test";
import { blankScenario, scenarioChanges, scenarioDraft, sliderScale } from "../src/goalScenarios.js";

test("scenario changes preserve explicit zero and distinguish a cleared date from the saved date", () => {
  assert.deepEqual(scenarioChanges(blankScenario), { changes: {}, errors: {} });
  const draft = { ...blankScenario, monthly_contribution: "0", one_time_contribution: "35,25", dateMode: "clear" };
  const result = scenarioChanges(draft);
  assert.deepEqual(result.changes, { monthly_contribution: "0.00", one_time_contribution: "35.25", target_date: null });
  assert.deepEqual(scenarioChanges(scenarioDraft(result.changes)), result);
  assert.equal(scenarioDraft({ target_amount: "100.00" }).dateMode, "saved");
});

test("scenario inputs reject invalid dates, negative savings assumptions, and zero targets", () => {
  const { errors } = scenarioChanges({
    ...blankScenario, target_amount: "0", expense_reduction: "-2", dateMode: "custom", target_date: "2027-02-29",
  });
  assert.deepEqual(Object.keys(errors), ["expense_reduction", "target_amount", "target_date"]);
  assert.deepEqual(scenarioChanges({ ...blankScenario, dateMode: "custom", target_date: "2028-02-29" }).changes,
    { target_date: "2028-02-29" });
});

test("slider spans lower and higher contributions and includes values beyond the original scale", () => {
  assert.deepEqual(sliderScale(100, 100), { min: 0, max: 200, step: 1, value: 100 });
  assert.ok(sliderScale(3500, 100).max >= 3500);
});
