import assert from "node:assert/strict";
import test from "node:test";
import { intensity, nextCellIndex, spendingBands, summarizeHeatmap } from "../src/spendingHeatmap.js";

test("category filtering changes amounts, counts, month totals and peak without losing empty days", () => {
  const source = [
    { date: "2024-01-31", total_spending: "18.01", transaction_count: 2,
      category_totals: { bills: "20.01", groceries: "-2.00" }, category_counts: { bills: 1, groceries: 1 } },
    { date: "2024-02-01", total_spending: "3.10", transaction_count: 2,
      category_totals: { groceries: "3.10" }, category_counts: { groceries: 2 } },
    { date: "2024-02-02", total_spending: "0.00", transaction_count: 0,
      category_totals: {}, category_counts: {} },
  ];
  const result = summarizeHeatmap(source, "groceries");
  assert.deepEqual(result.cells.map(({ cents, count, week, weekday }) => [cents, count, week, weekday]), [
    [-200, 1, 0, 3], [310, 2, 0, 4], [0, 0, 0, 5],
  ]);
  assert.deepEqual(result.months.slice(0, 3), [-200, 310, 0]);
  assert.equal(result.peak.date, "2024-02-01");
  assert.equal(summarizeHeatmap(source, "").peak.date, "2024-01-31");
  assert.equal(summarizeHeatmap(source, "health").hasActivity, false);
});

test("documented legend bands match cell levels down to individual cents", () => {
  for (const peak of [0, 1, 3, 4, 355, 1000]) {
    assert.equal(intensity(-1, peak), 0);
    assert.equal(intensity(0, peak), 0);
    for (let cents = 1; cents <= peak; cents++) {
      const band = spendingBands(peak).find(({ min, max }) => cents >= min && cents <= max);
      assert.equal(intensity(cents, peak), band.level);
    }
  }
});

test("keyboard movement follows calendar rows and weeks with partial edge weeks", () => {
  assert.equal(nextCellIndex("ArrowRight", 0, 3, 366), 7);
  assert.equal(nextCellIndex("ArrowDown", 0, 3, 366), 1);
  assert.equal(nextCellIndex("ArrowLeft", 0, 3, 366), 0);
  assert.equal(nextCellIndex("ArrowDown", 3, 6, 366), 3);
  assert.equal(nextCellIndex("Home", 2, 5, 366), 0);
  assert.equal(nextCellIndex("End", 364, 3, 366), 365);
  assert.equal(nextCellIndex("Enter", 1, 4, 366), null);
});
