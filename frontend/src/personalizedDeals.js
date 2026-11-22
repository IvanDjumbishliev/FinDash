const dayFormat = new Intl.DateTimeFormat("en", {
  day: "2-digit", month: "2-digit", year: "numeric", timeZone: "Europe/Sofia",
});

function sofiaDay(value) {
  const parts = Object.fromEntries(dayFormat.formatToParts(new Date(value)).map(({ type, value: part }) => [type, part]));
  return Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day));
}

export function expiresSoon(offer, now = Date.now()) {
  if (offer.expires_at) {
    const remaining = Date.parse(offer.expires_at) - now;
    return remaining > 0 && remaining <= 48 * 60 * 60 * 1000;
  }
  const ends = Date.parse(`${offer.expires_on}T00:00:00Z`);
  const days = (ends - sofiaDay(now)) / (24 * 60 * 60 * 1000);
  return Number.isFinite(days) && days >= 0 && days <= 1;
}

export function uniqueOffers(interests, field = "matches") {
  const seen = new Set();
  return interests.flatMap((interest) => interest[field].flatMap((offer) => {
    if (seen.has(offer.offer_id)) return [];
    seen.add(offer.offer_id);
    return [{ ...offer, interest }];
  }));
}

export function lowerThanReceipt(offer) {
  return offer.historical != null && Number(offer.historical.difference) > 0;
}

export function pricePerUnit(value, currency, unit) {
  const amount = Number(value);
  if (value == null || !Number.isFinite(amount) || !["EUR", "BGN"].includes(currency)) return "Unavailable";
  const price = new Intl.NumberFormat(undefined, {
    style: "currency", currency, currencyDisplay: "code", minimumFractionDigits: 2, maximumFractionDigits: 6,
  }).format(amount);
  return `${price} / ${unit === "item" ? "item" : unit === "l" ? "L" : unit}`;
}

export function offerExplanation(offer, preferredStores) {
  const reasons = [
    offer.interest.source === "inferred"
      ? `You approved ${offer.interest.name} from your receipts.`
      : `You saved ${offer.interest.name} in My Products.`,
  ];
  if (offer.relation === "exact") reasons.push("The product and package match the catalog evidence.");
  if (offer.relation === "comparable") reasons.push("The catalog supports this as a comparable alternative.");
  if (offer.relation === "needs_review") reasons.push("Product details need your review before this is treated as a match.");
  if (offer.brand_match) reasons.push("Matches your brand preference or saved brand.");
  if (offer.quantity_match) reasons.push("Matches your preferred or saved package size.");
  if (offer.user_reviewed) reasons.push("You reviewed this match.");
  if (preferredStores.includes(offer.retailer)) reasons.push("This is one of your preferred supermarkets.");
  return reasons;
}
