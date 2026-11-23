import test from "node:test";
import assert from "node:assert/strict";
import { addPantryReplenishment, groceryDraft, storeGroceryDraft } from "../src/groceryDraft.js";

test("replenishment adds a requested quantity to the current account draft", () => {
  const values = new Map();
  const storage = { getItem: (key) => values.get(key), setItem: (key, value) => values.set(key, value) };
  const product = { name: "Ориз", unit: "kg", brand: "Test", quantity: "0.100000" };
  const draft = addPantryReplenishment({ items: [], options: { currency: "BGN" } }, product, "0.75");
  assert.equal(draft.items[0].quantity, "0.75");
  assert.equal(draft.items[0].name, "Ориз");
  assert.equal(draft.options.currency, "BGN");
  assert.equal(storeGroceryDraft("owner", draft, storage), true);
  assert.deepEqual(groceryDraft("owner", storage), draft);
  assert.equal(groceryDraft("other", storage), null);
  assert.match(addPantryReplenishment(draft, product, "1").error, /already/);
  assert.match(addPantryReplenishment(draft, { name: "Eggs", unit: "item" }, "1.2").error, /valid/);
  assert.match(addPantryReplenishment(draft, product, "0").error, /valid/);
});
