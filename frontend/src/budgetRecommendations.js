export function reviewPayload(review, choices, confirmed) {
  const categories = review?.recommendations
    .filter(({ category }) => choices[category] === "accepted")
    .map(({ category }) => category) ?? [];
  if (!review?.review_id || !categories.length || confirmed !== true) return null;
  return { review_id: review.review_id, categories, confirmed: true };
}

export function recommendationRequest(period, consent) {
  return { period, use_gemini: consent === true };
}
