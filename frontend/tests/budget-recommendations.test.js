import assert from "node:assert/strict";
import { test } from "node:test";
import { recommendationRequest, reviewPayload } from "../src/budgetRecommendations.js";

const review = {
  review_id: "review-id",
  recommendations: [{ category: "groceries" }, { category: "bills" }, { category: "travel" }],
};

test("generation only enables Gemini for explicit consent", () => {
  for (const consent of [undefined, false, "true"]) {
    assert.deepEqual(recommendationRequest("2026-11", consent), { period: "2026-11", use_gemini: false });
  }
  assert.equal(recommendationRequest("2026-11", true).use_gemini, true);
});

test("approval requires confirmation and includes only accepted categories from the review", () => {
  const choices = { groceries: "accepted", bills: "rejected", unrelated: "accepted" };
  assert.equal(reviewPayload(review, choices, false), null);
  assert.equal(reviewPayload(review, { bills: "rejected" }, true), null);
  assert.equal(reviewPayload(null, choices, true), null);
  assert.deepEqual(reviewPayload(review, choices, true), {
    review_id: "review-id", categories: ["groceries"], confirmed: true,
  });
});
