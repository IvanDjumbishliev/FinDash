import assert from "node:assert/strict";
import { test } from "node:test";
import { bulkReviewChanges } from "../src/statementReview.js";

const clean = { row_id: 1, duplicate_matches: { existing: [], file: [] } };
const duplicate = { row_id: 2, duplicate_matches: { existing: [], file: [1] } };

test("bulk approval requires an explicit override for flagged rows", () => {
  assert.deepEqual(bulkReviewChanges([clean, duplicate], "approved", false), []);
  assert.deepEqual(bulkReviewChanges([clean, duplicate], "approved", true), [
    { row_id: 1, decision: "approved", allow_duplicate: false },
    { row_id: 2, decision: "approved", allow_duplicate: true },
  ]);
});

test("bulk rejection affects only selected rows and never sends a duplicate override", () => {
  assert.deepEqual(bulkReviewChanges([duplicate], "rejected", true), [
    { row_id: 2, decision: "rejected", allow_duplicate: false },
  ]);
});
