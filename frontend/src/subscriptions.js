export const billingCycles = {
  weekly: { label: "Weekly", perYear: 52 },
  monthly: { label: "Monthly", perYear: 12 },
  quarterly: { label: "Quarterly", perYear: 4 },
  yearly: { label: "Yearly", perYear: 1 },
};

export const categories = [
  "Uncategorized", "Entertainment", "Software", "Health & fitness",
  "Utilities", "Education", "Other",
];

export const statuses = {
  active: "Active",
  paused: "Paused",
  canceled: "Canceled",
  unconfirmed: "Unconfirmed",
};

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeZone: "UTC" });

export function formatDate(date) {
  return dateFormat.format(new Date(`${date}T00:00:00Z`));
}

export function formatMoney(value, currency) {
  return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(value);
}

function dateKey(date) {
  return [date.getFullYear(), date.getMonth() + 1, date.getDate()]
    .map((part, index) => String(part).padStart(index === 0 ? 4 : 2, "0"))
    .join("-");
}

export function subscriptionStatus(record) {
  if (record.status === "candidate") return "unconfirmed";
  return record.tracking_status || "active";
}

export function subscriptionOverview(records, today = new Date()) {
  const active = records.filter((record) => subscriptionStatus(record) === "active");
  const totals = {};
  const breakdown = {};
  for (const record of active) {
    const currency = record.currency;
    // Sum integer cents before converting the annual amount to a monthly estimate.
    const annualCents = Math.round(Number(record.estimated_amount) * 100)
      * billingCycles[record.billing_frequency].perYear;
    totals[currency] = (totals[currency] ?? 0) + annualCents;
    const category = record.category || "Uncategorized";
    breakdown[currency] ??= {};
    breakdown[currency][category] = (breakdown[currency][category] ?? 0) + annualCents;
  }

  const horizon = new Date(today);
  horizon.setDate(horizon.getDate() + 30);
  const first = dateKey(today);
  const last = dateKey(horizon);

  return {
    activeCount: active.length,
    totals: Object.entries(totals).sort().map(([currency, cents]) => ({
      currency, annual: cents / 100, monthly: cents / 1200,
    })),
    breakdown: Object.fromEntries(Object.entries(breakdown).map(([currency, values]) => [
      currency,
      Object.entries(values).map(([category, cents]) => ({ category, monthly: cents / 1200 }))
        .sort((a, b) => b.monthly - a.monthly),
    ])),
    upcoming: filterSubscriptions(records.filter((record) =>
      ["active", "unconfirmed"].includes(subscriptionStatus(record))
      && record.next_expected_payment >= first && record.next_expected_payment <= last
    ), "all", "renewal"),
  };
}

export function filterSubscriptions(records, filter, sort) {
  return records.filter((record) => filter === "all" || subscriptionStatus(record) === filter)
    .sort((a, b) => {
      if (sort === "price") {
        const difference = a.currency.localeCompare(b.currency)
          || Number(b.estimated_amount) - Number(a.estimated_amount);
        if (difference) return difference;
      }
      return a.next_expected_payment.localeCompare(b.next_expected_payment)
        || a.merchant.localeCompare(b.merchant);
    });
}

export function combineSubscriptions(records, local) {
  return [
    ...records.map((record) => ({ ...record, ...local.preferences[record.id] })),
    ...local.manual,
  ];
}

export function subscriptionEdit(draft, record, id) {
  const merchant = draft.merchant.trim();
  const currency = draft.currency.trim().toUpperCase();
  const amount = draft.estimated_amount.trim().replace(",", ".");
  const date = draft.next_expected_payment;
  if (!merchant || merchant.length > 255 || !/^\d{1,8}(?:\.\d{1,2})?$/.test(amount)
      || Number(amount) <= 0 || !/^\d{4}-\d{2}-\d{2}$/.test(date)
      || !/^[A-Z]{3}$/.test(currency) || !Object.hasOwn(billingCycles, draft.billing_frequency)
      || !categories.includes(draft.category)
      || !["active", "paused", "canceled"].includes(draft.tracking_status)) {
    throw new Error("Enter a merchant, a positive amount with up to two decimal places, and a valid payment date.");
  }
  const fields = {
    merchant, estimated_amount: amount, next_expected_payment: date,
  };
  const preferences = { category: draft.category, tracking_status: draft.tracking_status };
  if (record && !record.local) return { patch: fields, preferences };
  return {
    manual: {
      ...fields, ...preferences, id: record?.id ?? id, currency,
      billing_frequency: draft.billing_frequency, local: true, status: "confirmed",
    },
  };
}
