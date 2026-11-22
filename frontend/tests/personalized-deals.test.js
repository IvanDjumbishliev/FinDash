import assert from "node:assert/strict";
import { test } from "node:test";
import { expiresSoon, lowerThanReceipt, uniqueOffers } from "../src/personalizedDeals.js";
import { addCatalogPackage, groceryDraft, storeGroceryDraft } from "../src/groceryDraft.js";

test("expiry uses Sofia dates and respects a retailer's exact cutoff", () => {
  const now = Date.parse("2026-11-21T23:00:00Z");
  assert.equal(expiresSoon({ expires_on: "2026-11-21" }, now), false);
  assert.equal(expiresSoon({ expires_on: "2026-11-23" }, now), true);
  assert.equal(expiresSoon({ expires_on: "2026-11-24" }, now), false);
  assert.equal(expiresSoon({ expires_at: "2026-11-23T22:00:00Z" }, now), true);
  assert.equal(expiresSoon({ expires_at: "2026-11-21T22:00:00Z" }, now), false);
});

test("receipt comparison uses only the validated difference and deduplicates ranked offers", () => {
  assert.ok(lowerThanReceipt({ historical: { difference: "0.001" } }));
  assert.ok(!lowerThanReceipt({ historical: { difference: "-1.20" }, discount_percent: 30 }));
  assert.ok(!lowerThanReceipt({ discount_percent: 30 }));
  const offers = uniqueOffers([
    { id: 1, matches: [{ offer_id: 2 }] }, { id: 3, matches: [{ offer_id: 2 }] },
  ]);
  assert.equal(offers.length, 1);
  assert.equal(offers[0].interest.id, 1);
});

test("optimizer draft adds one package, keeps other items and isolates account drafts", () => {
  const offer = { id: 1, name: "Milk 1 L", quantity: "1", unit: "l", currency: "EUR", brand: "Dairy", price: "2.00" };
  const draft = addCatalogPackage(null, offer);
  assert.equal(draft.items[0].quantity, "1");
  assert.equal(draft.items[0].preferred_brand, "Dairy");
  assert.equal(draft.items[0].price, undefined);
  assert.match(addCatalogPackage(draft, offer).error, /already/);
  const next = addCatalogPackage(draft, { ...offer, id: 2, name: "Eggs", quantity: "6", unit: "item", currency: "BGN" });
  assert.equal(next.items.length, 2);
  assert.equal(next.options.currency, "EUR");
  const values = new Map();
  const storage = { getItem: (key) => values.get(key), setItem: (key, value) => values.set(key, value) };
  assert.ok(storeGroceryDraft(1, next, storage));
  assert.deepEqual(groceryDraft(1, storage), JSON.parse(JSON.stringify(next)));
  assert.equal(groceryDraft(2, storage), null);
});
