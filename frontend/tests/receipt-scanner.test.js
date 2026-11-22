import assert from "node:assert/strict";
import { test } from "node:test";
import { confirmationBody, receiptTotals, reviewFields, validateReceiptImages } from "../src/receiptScanner.js";

test("validates photo selection without assuming desktop MIME metadata", () => {
  assert.equal(validateReceiptImages([{ name: "Camera.HEIC", size: 1500 }]), "");
  assert.match(validateReceiptImages([{ name: "invoice.pdf", size: 2000 }]), /Choose a JPEG/);
  assert.match(validateReceiptImages([{ name: "large.png", size: 9 * 1024 * 1024 }]), /8 MB/);
});

test("signed reviewed amounts reconcile exactly in integer cents", () => {
  assert.deepEqual(receiptTotals([{ line_total: "0,10" }, { line_total: "0.20" }, { line_total: "-0.15" }], "0.15"), {
    itemTotal: 15, receiptTotal: 15, difference: 0,
  });
  assert.equal(receiptTotals([{ line_total: "" }], "2.00").itemTotal, null);
});

test("sends only reviewed fields and preserves original date offset and currency", () => {
  const source = { merchant: "Test", currency: "BGN", total: "3,00", purchased_at: "2026-11-23T13:40:00+02:00",
    items: [{ original_description: "Milk", line_total: "3,00", discount: null, normalized_name: "milk", quantity: "1" }] };
  const fields = reviewFields(source);
  const body = confirmationBody("signed-token", fields);
  assert.equal(body.purchased_at, source.purchased_at);
  assert.equal(body.currency, "BGN");
  assert.equal(body.total, "3.00");
  assert.equal(body.items[0].line_total, "3.00");
  assert.ok(!Object.hasOwn(body.items[0], "normalized_name"));
  assert.equal(confirmationBody("signed-token", { ...fields, date: "2026-07-23", time: "16:00" }).purchased_at,
    "2026-07-23T16:00:00+03:00");
  assert.throws(() => confirmationBody("signed-token", { ...fields, date: "2026-03-29", time: "03:30" }), /valid purchase date/);
});
