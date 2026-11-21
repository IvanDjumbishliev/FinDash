const statuses = {
  quoted: "Quote available",
  stale: "Stale quote",
  currency_mismatch: "Currency mismatch",
  unavailable: "Quote unavailable",
  quote_limit: "Quote limit reached",
};

export function quoteStatus(status) {
  return statuses[status] ?? "Quote unavailable";
}

export function formatTimestamp(value) {
  const date = new Date(value);
  return !value || Number.isNaN(date.getTime()) ? "" : new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium", timeStyle: "short",
  }).format(date);
}

export function allocation(snapshot) {
  const market = snapshot.performance.valuation_complete;
  return {
    label: market ? "Market value" : "Open FIFO cost basis",
    rows: snapshot.holdings.map((holding) => ({
      ticker: holding.ticker, value: Number(market ? holding.market_value : holding.cost_basis),
    })).filter((item) => Number.isFinite(item.value) && item.value > 0),
  };
}

export function marketFreshness(snapshot) {
  const { valued_position_count: valued, open_position_count: open } = snapshot.performance;
  const oldest = snapshot.holdings
    .filter((holding) => holding.market_quote.status === "quoted" && holding.market_quote.timestamp)
    .map((holding) => new Date(holding.market_quote.timestamp).getTime())
    .filter(Number.isFinite)
    .sort((a, b) => a - b)[0];
  return { valued, open, oldest: Number.isFinite(oldest) ? new Date(oldest).toISOString() : null };
}

export function responseError(error, fallback) {
  function collect(value) {
    if (typeof value === "string") return [value];
    if (Array.isArray(value)) return value.flatMap(collect);
    return value && typeof value === "object" ? Object.values(value).flatMap(collect) : [];
  }
  return collect(error.response?.data).join(" ") || fallback;
}

export function orderId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((value) => value.toString(16).padStart(2, "0")).join("");
  return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join("-");
}
