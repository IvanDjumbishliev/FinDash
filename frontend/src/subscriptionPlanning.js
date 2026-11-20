import { subscriptionStatus } from "./subscriptions.js";

export const renewalWindows = [7, 30, 90];
const cycleMonths = { monthly: 1, quarterly: 3, yearly: 12 };

function dateString(date) {
  return date.toISOString().slice(0, 10);
}

function addDays(value, days) {
  const date = new Date(`${value}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return dateString(date);
}

export function renewalWindow(entries, today, days) {
  const end = addDays(today, days);
  return entries.filter(({ date }) => date >= today && date < end);
}

function projectRecord(record, today, preferences, windowDays = 90) {
  const first = record.next_expected_payment;
  const end = addDays(today, windowDays);
  const origin = new Date(`${first}T00:00:00Z`);
  const day = origin.getUTCDate();
  const month = origin.getUTCMonth();
  const year = origin.getUTCFullYear();
  const anchor = record.billing_anchor_day
    || (day === new Date(Date.UTC(year, month + 1, 0)).getUTCDate() ? 31 : day);
  const months = cycleMonths[record.billing_frequency];
  const lead = addDays(today, preferences?.reminder_lead_days ?? 0);
  const start = new Date(`${today}T00:00:00Z`);
  const elapsedMonths = (start.getUTCFullYear() - year) * 12 + start.getUTCMonth() - month;
  let period = Math.max(0, months ? Math.floor(elapsedMonths / months)
    : Math.floor((start - origin) / (7 * 86400000)));
  const entries = [];

  for (;;) {
    const targetMonth = month + period * months;
    const due = months
      ? dateString(new Date(Date.UTC(year, targetMonth, Math.min(anchor,
        new Date(Date.UTC(year, targetMonth + 1, 0)).getUTCDate()))))
      : addDays(first, period * 7);
    if (due >= end) return entries;
    if (due >= today) entries.push({
      subscription_id: record.id,
      date: due,
      reminder_due: Boolean(preferences?.renewal_reminders && due <= lead),
    });
    period += 1;
  }
}

export function planningCalendar(plan, records, preferences) {
  const eligible = records.filter((record) =>
    ["active", "unconfirmed"].includes(subscriptionStatus(record))
  );
  const byId = new Map(eligible.map((record) => [record.id, record]));
  return [...plan.renewals, ...eligible.filter((record) => record.local)
    .flatMap((record) => projectRecord(record, plan.as_of, preferences))]
    .filter((entry) => byId.has(entry.subscription_id))
    .map((entry) => ({ ...entry, record: byId.get(entry.subscription_id) }))
    .sort((a, b) => a.date.localeCompare(b.date) || a.record.merchant.localeCompare(b.record.merchant));
}

export function preferencePayload(draft) {
  const raw = String(draft.reminder_lead_days).trim();
  const days = Number(raw);
  if (!/^\d+$/.test(raw) || !Number.isInteger(days) || days > 30) {
    throw new Error("Enter a reminder lead time from 0 to 30 days.");
  }
  return {
    renewal_reminders: draft.renewal_reminders,
    reminder_lead_days: days,
    monthly_summary: draft.monthly_summary,
  };
}

export function calendarMonths(today, days) {
  const first = new Date(`${today.slice(0, 7)}-01T00:00:00Z`);
  const last = addDays(today, days - 1).slice(0, 7);
  const months = [];
  while (dateString(first).slice(0, 7) <= last) {
    months.push(dateString(first).slice(0, 7));
    first.setUTCMonth(first.getUTCMonth() + 1);
  }
  return months;
}

export function calendarMonthDays(month) {
  const first = new Date(`${month}-01T00:00:00Z`);
  const startOffset = (first.getUTCDay() + 6) % 7;
  const count = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 0)).getUTCDate();
  return [
    ...Array(startOffset).fill(null),
    ...Array.from({ length: count }, (_, i) => addDays(`${month}-01`, i)),
  ];
}


export function manualDuplicatePairs(records, today) {
  const groups = new Map();
  for (const record of records) {
    const merchant = record.normalized_merchant || record.merchant.normalize("NFKC")
      .toLowerCase().replace(/^(?:card payment|pos|payment to)\b[ *:/-]*/, "")
      .replace(/(?:\s+(?:ref|txn|order|invoice)[ #*:-]*\d[\w-]*|[ *#]+\d{4,})$/, "")
      .replace(/^www\./, "").replace(/\.(?:com|net|org|bg|co\.uk)$/, "")
      .replace(/[^\p{L}\p{N}]/gu, "");
    if (!merchant) continue;
    const key = `${merchant}:${record.currency}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(record);
  }

  const pairs = [];
  for (const group of groups.values()) {
    if (group.length < 2 || !group.some((record) => record.local)) continue;
    const dates = group.map((record) =>
      new Set(projectRecord(record, today, null, 366).map(({ date }) => date)));
    for (const [i, left] of group.entries()) {
      for (let j = i + 1; j < group.length; j += 1) {
        const right = group[j];
        if (!left.local && !right.local) continue;
        const overlap = [...dates[i]].find((due) => [-2, -1, 0, 1, 2]
          .some((offset) => dates[j].has(addDays(due, offset))));
        if (overlap) pairs.push({ subscription_ids: [left.id, right.id], overlap_date: overlap });
      }
    }
  }
  return pairs;
}
