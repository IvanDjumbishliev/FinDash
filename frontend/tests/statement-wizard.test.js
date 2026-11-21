import assert from "node:assert/strict";
import { test } from "node:test";
import { importSummary, importSteps, validateStatementFiles } from "../src/statementWizard.js";

test("file validation accepts one PDF or CSV and rejects other, empty or oversized selections", () => {
  assert.equal(validateStatementFiles([{ name: "BANK.PDF", size: 90 }]), "");
  assert.equal(validateStatementFiles([{ name: "bank.csv", size: 1 }]), "");
  assert.match(validateStatementFiles([]), /exactly one/);
  assert.match(validateStatementFiles([{ name: "bank.xlsx", size: 100 }]), /Unsupported/);
  assert.match(validateStatementFiles([{ name: "bank.csv", size: 0 }]), /empty/);
  assert.match(validateStatementFiles([{ name: "bank.csv", size: 10 * 1024 * 1024 + 1 }]), /10 MB/);
});

test("confirmation counts approved rows and includes excluded and pending rows in the skipped estimate", () => {
  const row = (decision, file = []) => ({ decision, duplicate_matches: { file, existing: [] } });
  assert.deepEqual(importSteps, ["Upload", "Parse", "Review", "Confirm", "Complete"]);
  assert.deepEqual(importSummary([
    row("approved"), row("approved", [1]), row("rejected"), row("pending", [1]),
  ]), { total: 4, selected: 2, duplicates: 2, skipped: 2 });
});
