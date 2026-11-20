import { useEffect, useState } from "react";
import PropTypes from "prop-types";
import api from "../api";
import {
  formatDate, formatMoney, subscriptionOverview, subscriptionStatus,
} from "../subscriptions";
import {
  calendarMonthDays, calendarMonths, manualDuplicatePairs, planningCalendar, preferencePayload, renewalWindow, renewalWindows,
} from "../subscriptionPlanning";

const root = "/api/subscriptions/";
const monthLabel = new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric", timeZone: "UTC" });
const weekdayLabel = new Intl.DateTimeFormat(undefined, { weekday: "short", timeZone: "UTC" });
const weekdays = Array.from({ length: 7 }, (_, i) => weekdayLabel.format(new Date(Date.UTC(2026, 0, 5 + i))));
const formatMonth = (month) => monthLabel.format(new Date(`${month}-01T00:00:00Z`));

function RenewalCalendar({ entries, today }) {
  const [days, setDays] = useState(30);
  const [selectedMonth, setSelectedMonth] = useState("");
  const [selectedDay, setSelectedDay] = useState("");
  const months = calendarMonths(today, days);
  const month = months.includes(selectedMonth) ? selectedMonth : months[0];
  const windowEntries = renewalWindow(entries, today, days);
  const counts = new Map();
  for (const entry of windowEntries) counts.set(entry.date, (counts.get(entry.date) || 0) + 1);
  const visible = selectedDay ? windowEntries.filter((entry) => entry.date === selectedDay) : windowEntries;

  return (
    <section className="subscription-panel renewal-calendar" aria-labelledby="renewal-calendar-title">
      <div className="subscription-heading">
        <div>
          <h2 id="renewal-calendar-title">Renewal calendar</h2>
          <p className="subscription-note">Estimated dates and amounts. Select a marked date to see its payments.</p>
        </div>
        <div className="subscription-actions" role="group" aria-label="Renewal window">
          {renewalWindows.map((window) => (
            <button key={window} type="button" aria-pressed={window === days} onClick={() => {
              setDays(window);
              setSelectedDay("");
            }}>Next {window} days</button>
          ))}
        </div>
      </div>
      <div className="renewal-calendar-content">
        <div>
          <label className="subscription-chart-currency">Calendar month
            <select value={month} onChange={(event) => {
              setSelectedMonth(event.target.value);
              setSelectedDay("");
            }}>
              {months.map((item) => <option key={item} value={item}>{formatMonth(item)}</option>)}
            </select>
          </label>
          <div className="renewal-days">
            {weekdays.map((weekday, index) => <span className="renewal-weekday" key={index}>{weekday}</span>)}
            {calendarMonthDays(month).map((day, index) => {
              const count = counts.get(day);
              return count ? (
                <button key={day} type="button" aria-pressed={selectedDay === day}
                  aria-label={`${formatDate(day)}, ${count} estimated ${count === 1 ? "renewal" : "renewals"}`}
                  onClick={() => setSelectedDay(selectedDay === day ? "" : day)}>
                  {Number(day.slice(-2))}
                  <small>{count}</small>
                </button>
              ) : <span key={day ?? `blank-${index}`}>{day && Number(day.slice(-2))}</span>;
            })}
          </div>
        </div>
        <div>
          <div className="subscription-heading">
            <h3>{selectedDay ? formatDate(selectedDay) : "Upcoming estimated payments"}</h3>
            {selectedDay && <button type="button" onClick={() => setSelectedDay("")}>Show all days</button>}
          </div>
          {visible.length ? (
            <ul className="subscription-renewals">
              {visible.map(({ record, date, reminder_due }) => (
                <li key={`${record.id}:${date}`}>
                  <div>
                    <strong>{record.merchant}</strong>
                    <p className="subscription-note">
                      {record.status === "candidate" ? "Predicted subscription" : "Confirmed schedule"}
                      {reminder_due && " · Reminder due"}
                    </p>
                  </div>
                  <div>
                    <time dateTime={date}>{formatDate(date)}</time>
                    <p>{formatMoney(record.estimated_amount, record.currency)} est.</p>
                  </div>
                </li>
              ))}
            </ul>
          ) : <p className="subscription-note">No estimated payments in this window.</p>}
        </div>
      </div>
    </section>
  );
}

RenewalCalendar.propTypes = {
  entries: PropTypes.arrayOf(PropTypes.object).isRequired,
  today: PropTypes.string.isRequired,
};

function ReminderSettings({ preferences, onSave }) {
  const [draft, setDraft] = useState(preferences);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);
  const disabled = busy || (
    draft.renewal_reminders === preferences.renewal_reminders
    && draft.monthly_summary === preferences.monthly_summary
    && String(draft.reminder_lead_days) === String(preferences.reminder_lead_days)
  );

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const saved = await onSave(preferencePayload(draft));
      setDraft(saved);
      setMessage({ text: "Reminder preferences saved.", error: false });
    } catch (error) {
      setMessage({
        text: error.isAxiosError ? "Could not save reminder preferences. Try again." : error.message,
        error: true,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="subscription-panel reminder-settings" onSubmit={submit} aria-labelledby="subscription-reminder-title">
      <h2 id="subscription-reminder-title">Reminders and summary</h2>
      <p className="subscription-note">Renewal reminders appear on this page for confirmed subscriptions.</p>
      <fieldset disabled={busy}>
        <label>
          <input type="checkbox" checked={draft.renewal_reminders} onChange={(event) =>
            setDraft({ ...draft, renewal_reminders: event.target.checked })} />
          Show renewal reminders
        </label>
        <label>
          Days before renewal
          <input type="number" min="0" max="30" step="1" required value={draft.reminder_lead_days}
            onChange={(event) => setDraft({ ...draft, reminder_lead_days: event.target.value })} />
        </label>
        <label>
          <input type="checkbox" checked={draft.monthly_summary} onChange={(event) =>
            setDraft({ ...draft, monthly_summary: event.target.checked })} />
          Show a monthly summary
        </label>
      </fieldset>
      <button type="submit" disabled={disabled}>{busy ? "Saving…" : "Save preferences"}</button>
      {message && <p role={message.error ? "alert" : "status"}>{message.text}</p>}
    </form>
  );
}

ReminderSettings.propTypes = {
  preferences: PropTypes.shape({
    renewal_reminders: PropTypes.bool.isRequired,
    reminder_lead_days: PropTypes.number.isRequired,
    monthly_summary: PropTypes.bool.isRequired,
  }).isRequired,
  onSave: PropTypes.func.isRequired,
};

export default function SubscriptionPlanning({ records, serverRecords }) {
  const [plan, setPlan] = useState(null);
  const [preferences, setPreferences] = useState(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      setError("");
      try {
        const [planning, settings] = await Promise.all([
          api.get(`${root}planning/`, { signal: controller.signal, timeout: 15000 }),
          api.get(`${root}preferences/`, { signal: controller.signal, timeout: 15000 }),
        ]);
        if (!controller.signal.aborted) {
          setPlan(planning.data);
          setPreferences(settings.data);
        }
      } catch {
        if (!controller.signal.aborted) setError("Could not load the renewal calendar and settings.");
      }
    }
    load();
    return () => controller.abort();
  }, [serverRecords, reload]);

  async function savePreferences(payload) {
    const { data } = await api.patch(`${root}preferences/`, payload);
    setPreferences(data);
    setReload((previous) => previous + 1);
    return data;
  }

  if (!plan || !preferences) {
    return error ? (
      <div className="subscription-message">
        <p role="alert">{error}</p>
        <button type="button" onClick={() => setReload((value) => value + 1)}>Retry calendar</button>
      </div>
    ) : <p className="subscription-message" role="status">Loading renewal calendar…</p>;
  }

  const entries = planningCalendar(plan, records, preferences);
  const reminders = entries.filter(({ reminder_due }) => reminder_due && preferences.renewal_reminders);
  const byId = new Map(records.filter((record) =>
    ["active", "unconfirmed"].includes(subscriptionStatus(record))
  ).map((record) => [record.id, record]));
  const increases = plan.price_increases.filter(({ subscription_id }) => byId.has(subscription_id));
  const duplicates = [
    ...plan.duplicates.filter(({ subscription_ids }) => subscription_ids.every((id) => byId.has(id))),
    ...manualDuplicatePairs([...byId.values()], plan.as_of),
  ];
  const month = plan.as_of.slice(0, 7);
  const monthEntries = entries.filter(({ date, record }) => date.startsWith(month) && record.status === "confirmed");
  const overview = preferences.monthly_summary ? subscriptionOverview(records) : null;

  return (
    <>
      {error && <div className="subscription-message" role="alert">
        {error} Showing the last available calendar.
        <button type="button" onClick={() => setReload((value) => value + 1)}>Retry calendar</button>
      </div>}
      {reminders.length > 0 && (
        <section className="subscription-panel" aria-label="Renewal reminders due">
          <h2>Renewal reminders due</h2>
          <ul className="subscription-renewals">
            {reminders.map(({ record, date }) => (
              <li key={`${record.id}:${date}`}><strong>{record.merchant}</strong><time dateTime={date}>{formatDate(date)}</time></li>
            ))}
          </ul>
        </section>
      )}
      <RenewalCalendar entries={entries} today={plan.as_of} />

      <div className="subscription-overview subscription-planning-options">
        <ReminderSettings preferences={preferences} onSave={savePreferences} />
        <section className="subscription-panel" aria-labelledby="subscription-alerts-heading">
          <h2 id="subscription-alerts-heading">Patterns to review</h2>
          <p className="subscription-note">Possible duplicates and price increases are based on schedules and recorded charges. Review them before making changes.</p>
          {increases.length + duplicates.length === 0 ? <p>No patterns flagged for review.</p> : (
            <ul className="subscription-renewals">
              {duplicates.map(({ subscription_ids: [left, right], overlap_date }) => (
                <li key={`duplicate:${left}:${right}`}>
                  <span><strong>Possible duplicate</strong><br />
                    {byId.get(left).merchant} and {byId.get(right).merchant}
                  </span>
                  <span>Schedules overlap around {formatDate(overlap_date)}.</span>
                </li>
              ))}
              {increases.map(({ subscription_id: id, previous_amount, recent_amount }) => (
                <li key={`price:${id}`}>
                  <span><strong>Possible price increase</strong><br />{byId.get(id).merchant}</span>
                  <span>{formatMoney(previous_amount, byId.get(id).currency)} → {formatMoney(recent_amount, byId.get(id).currency)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {overview && (
        <section className="subscription-panel" aria-labelledby="subscription-monthly-heading">
          <h2 id="subscription-monthly-heading">{formatMonth(month)} subscription summary</h2>
          <p>{overview.activeCount} active subscriptions · {monthEntries.length} estimated payments remaining this month</p>
          <ul className="subscription-renewals">
            {overview.totals.map(({ currency, monthly, annual }) => {
              const remaining = monthEntries.reduce((sum, { record }) =>
                sum + (record.currency === currency ? Math.round(Number(record.estimated_amount) * 100) : 0), 0) / 100;
              return (
                <li key={currency}>
                  <strong>{currency}</strong>
                  <span>{formatMoney(remaining, currency)} estimated for the rest of this month</span>
                  <span>{formatMoney(monthly, currency)}/month · {formatMoney(annual, currency)}/year projected</span>
                </li>
              );
            })}
          </ul>
          <p className="subscription-note">Based on active confirmed schedules and manual entries. Charges and dates can change.</p>
        </section>
      )}
    </>
  );
}

SubscriptionPlanning.propTypes = {
  records: PropTypes.arrayOf(PropTypes.object).isRequired,
  serverRecords: PropTypes.arrayOf(PropTypes.object).isRequired,
};
