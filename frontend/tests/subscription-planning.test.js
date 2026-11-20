import { test } from "node:test";
import assert from "node:assert/strict";
import {
  calendarMonthDays, calendarMonths, manualDuplicatePairs, planningCalendar,
  preferencePayload, renewalWindow,
} from "../src/subscriptionPlanning.js";

const settings = { renewal_reminders: true, reminder_lead_days: 3, monthly_summary: false };

test("renewal windows include today and exclude their end dates", () => {
  const items = ["2026-11-21", "2026-11-28", "2026-12-20", "2026-12-21", "2027-02-19"]
    .map((date) => ({ date }));
  assert.equal(renewalWindow(items, "2026-11-21", 7).length, 1);
  assert.equal(renewalWindow(items, "2026-11-21", 30).length, 3);
  assert.equal(renewalWindow(items, "2026-11-21", 90).length, 4);
});

test("calendar months cross year boundaries and February includes leap day", () => {
  assert.deepEqual(calendarMonths("2026-12-28", 7), ["2026-12", "2027-01"]);
  const days = calendarMonthDays("2028-02");
  assert.equal(days[0], null);
  assert.equal(days[1], "2028-02-01");
  assert.equal(days.at(-1), "2028-02-29");
});

test("calendar merges server and manual occurrences, suppressing inactive tracking", () => {
  const plan = {
    as_of: "2026-02-26",
    renewals: [
      { subscription_id: 1, date: "2026-03-01", reminder_due: false },
      { subscription_id: 2, date: "2026-03-02", reminder_due: true },
    ],
  };
  const entries = planningCalendar(plan, [
    { id: 1, merchant: "Predicted", status: "candidate" },
    { id: 2, merchant: "Paused", status: "confirmed", tracking_status: "paused" },
    { id: "local", local: true, merchant: "Manual", status: "confirmed",
      billing_frequency: "monthly", next_expected_payment: "2026-01-31" },
  ], settings);
  assert.deepEqual(entries.map(({ date, reminder_due, record }) => [date, reminder_due, record.id]), [
    ["2026-02-28", true, "local"], ["2026-03-01", false, 1],
    ["2026-03-31", false, "local"], ["2026-04-30", false, "local"],
  ]);
});

test("manual duplicates require normalized merchant, currency, and overlapping dates", () => {
  const records = [
    { id: 1, merchant: "Cloud Service", normalized_merchant: "cloudservice", currency: "EUR",
      billing_frequency: "monthly", next_expected_payment: "2026-11-10" },
    { id: "manual", local: true, merchant: "Cloud-Service.com 2345", currency: "EUR",
      billing_frequency: "quarterly", next_expected_payment: "2026-12-11" },
    { id: "unrelated", local: true, merchant: "Cloud Service", currency: "USD",
      billing_frequency: "monthly", next_expected_payment: "2026-12-10" },
  ];
  assert.deepEqual(manualDuplicatePairs(records, "2026-11-21"), [
    { subscription_ids: [1, "manual"], overlap_date: "2026-12-10" },
  ]);
});

test("reminder settings build a bounded payload and allow same-day reminders", () => {
  assert.deepEqual(preferencePayload({ ...settings, reminder_lead_days: "0", monthly_summary: true }), {
    renewal_reminders: true, reminder_lead_days: 0, monthly_summary: true,
  });
  for (const value of ["", "31", "-1", "2.5"]) {
    assert.throws(() => preferencePayload({ ...settings, reminder_lead_days: value }));
  }
});
