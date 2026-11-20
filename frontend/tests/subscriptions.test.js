import { test } from "node:test";
import assert from "node:assert/strict";
import {
  combineSubscriptions, filterSubscriptions, subscriptionEdit, subscriptionOverview,
} from "../src/subscriptions.js";

function record(id, overrides = {}) {
  return {
    id, merchant: `Merchant ${id}`, status: "confirmed", estimated_amount: "12.00",
    currency: "EUR", billing_frequency: "monthly", next_expected_payment: "2026-12-03",
    ...overrides,
  };
}

test("monthly and annual estimates use all billing cycles and keep currencies separate", () => {
  const overview = subscriptionOverview([
    record(1, { billing_frequency: "weekly", estimated_amount: "6.00", category: "Software" }),
    record(2, { category: "Software" }),
    record(3, { billing_frequency: "quarterly", estimated_amount: "30.00" }),
    record(4, { billing_frequency: "yearly", estimated_amount: "60.00", currency: "USD" }),
    record(5, { status: "candidate" }),
    record(6, { tracking_status: "paused" }),
    record(7, { tracking_status: "canceled" }),
  ]);
  assert.equal(overview.activeCount, 4);
  assert.deepEqual(overview.totals, [
    { currency: "EUR", annual: 576, monthly: 48 },
    { currency: "USD", annual: 60, monthly: 5 },
  ]);
  assert.deepEqual(overview.breakdown.EUR, [
    { category: "Software", monthly: 38 },
    { category: "Uncategorized", monthly: 10 },
  ]);
});

test("status filters and price ordering work across local and server entries", () => {
  const records = combineSubscriptions(
    [record(1), record(2), record(3, { status: "candidate" }), record(4)],
    { preferences: { 2: { tracking_status: "paused" }, 4: { tracking_status: "canceled" } },
      manual: [record("manual", { estimated_amount: "25.00" })] }
  );
  for (const [status, ids] of [
    ["active", ["manual", 1]], ["paused", [2]], ["canceled", [4]], ["unconfirmed", [3]],
  ]) {
    assert.deepEqual(filterSubscriptions(records, status, "price").map(({ id }) => id), ids);
  }
});

test("editing uses only Stage 1 writable fields and validates manual entries", () => {
  const draft = { ...record(1), merchant: "  New name ", category: "Software", tracking_status: "paused" };
  assert.deepEqual(subscriptionEdit(draft, record(1)), {
    patch: { merchant: "New name", estimated_amount: "12.00", next_expected_payment: "2026-12-03" },
    preferences: { category: "Software", tracking_status: "paused" },
  });
  assert.equal(subscriptionEdit(draft, null, "new").manual.local, true);
  assert.throws(() => subscriptionEdit({ ...draft, estimated_amount: "-2" }, null));
});
