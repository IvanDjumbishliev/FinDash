import assert from "node:assert/strict";
import { test } from "node:test";
import { code128, drawingSVG, ean13, ean8, qrcode, upca } from "@bwip-js/browser";
import { drawLoyaltyCode, loyaltyCodeOptions } from "../src/loyaltyCode.js";

test("supported encoders accept layout options and the exact original identifier", () => {
  for (const [format, encoder, identifier] of [
    ["code128", code128, "MEM-001234"], ["qrcode", qrcode, "MEM-001234"],
    ["ean8", ean8, "96385074"], ["ean13", ean13, "5901234123457"], ["upca", upca, "036000291452"],
  ]) {
    const options = loyaltyCodeOptions(format, identifier);
    assert.equal(options.text, identifier);
    assert.match(encoder(options, drawingSVG()), /^<svg /);
  }
  assert.equal(drawLoyaltyCode(null, "none", "MEM-001234"), false);
  assert.equal(drawLoyaltyCode(null, "toString", "MEM-001234"), false);
});
