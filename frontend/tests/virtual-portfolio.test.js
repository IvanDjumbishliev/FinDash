import assert from "node:assert/strict";
import test from "node:test";
import { allocation, marketFreshness, quoteStatus } from "../src/virtualPortfolio.js";

test("allocation applies one consistent valuation basis to every holding", () => {
  const snapshot = {
    performance: { valuation_complete: false },
    holdings: [{ ticker: "A", market_value: "100", cost_basis: "80" }, { ticker: "B", market_value: null, cost_basis: "35" }],
  };
  assert.deepEqual(allocation(snapshot), { label: "Open FIFO cost basis", rows: [
    { ticker: "A", value: 80 }, { ticker: "B", value: 35 },
  ] });
  snapshot.performance.valuation_complete = true;
  snapshot.holdings[1].market_value = "50";
  assert.deepEqual(allocation(snapshot), { label: "Market value", rows: [
    { ticker: "A", value: 100 }, { ticker: "B", value: 50 },
  ] });
});

test("freshness ignores stale and mismatched quotes and reports the oldest usable quote", () => {
  const snapshot = {
    performance: { valued_position_count: 2, open_position_count: 4 },
    holdings: [
      { market_quote: { status: "stale", timestamp: "2026-01-01" } },
      { market_quote: { status: "quoted", timestamp: "2026-01-09" } },
      { market_quote: { status: "currency_mismatch", timestamp: "2026-01-03" } },
      { market_quote: { status: "quoted", timestamp: "2026-01-08" } },
    ],
  };
  assert.deepEqual(marketFreshness(snapshot), { valued: 2, open: 4, oldest: "2026-01-08T00:00:00.000Z" });
  assert.equal(quoteStatus("currency_mismatch"), "Currency mismatch");
});
