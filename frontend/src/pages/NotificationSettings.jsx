import { useEffect, useState } from "react";
import { FiArrowLeft, FiSettings } from "react-icons/fi";
import { Link } from "react-router-dom";
import api from "../api";
import { ACCESS_TOKEN } from "../constants";
import { notificationAccount, useNotificationInbox } from "../components/notificationContext";
import { categories, notificationPath } from "../notifications";

const path = `${notificationPath}preferences/`;
const emptyRule = { ticker: "", currency: "USD", direction: "above", target: "" };
function canonicalPrice(value) {
  const [whole, fraction = ""] = value.split(".");
  return [whole.replace(/^0+(?=[0-9])/, ""), fraction.replace(/0+$/, "")].join(".");
}

const authHeaders = () => ({ Authorization: `Bearer ${localStorage.getItem(ACCESS_TOKEN)}` });

export default function NotificationSettings() {
  const { account } = useNotificationInbox();
  const [attempt, setAttempt] = useState(0);
  const [preferences, setPreferences] = useState(null);
  const [savedPreferences, setSavedPreferences] = useState(null);
  const [rule, setRule] = useState(emptyRule);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (account === null || account !== notificationAccount()) return;
    const controller = new AbortController();
    api.get(path, { signal: controller.signal, timeout: 8_000, headers: authHeaders() }).then(({ data }) => {
      if (!controller.signal.aborted && account === notificationAccount()) {
        setSavedPreferences(data);
        setPreferences(data);
      }
    }).catch(() => {
      if (!controller.signal.aborted && account === notificationAccount()) setLoadError(true);
    });
    return () => controller.abort();
  }, [account, attempt]);

  const changes = {};
  if (preferences && savedPreferences) {
    const changedCategories = Object.entries(preferences.categories)
      .filter(([key, value]) => value !== savedPreferences.categories[key]);
    if (changedCategories.length) changes.categories = Object.fromEntries(changedCategories);
    if (preferences.stock_alerts !== savedPreferences.stock_alerts) changes.stock_alerts = preferences.stock_alerts;
  }
  const dirty = Object.keys(changes).length > 0;

  async function save() {
    if (!dirty || saving || account !== notificationAccount()) return;
    setSaving(true);
    setMessage("");
    try {
      const { data } = await api.patch(path, changes, { timeout: 8_000, headers: authHeaders() });
      if (account === notificationAccount()) {
        setSavedPreferences(data);
        setPreferences(data);
        setMessage("Notification settings saved.");
      }
    } catch (error) {
      if (account === notificationAccount()) {
        const stockErrors = error.response?.data?.stock_alerts;
        const detail = Array.isArray(stockErrors) && stockErrors.find((value) => typeof value === "string");
        setMessage(detail || "Could not save settings. Check your price rules and try again.");
      }
    } finally {
      setSaving(false);
    }
  }

  function addRule(event) {
    event.preventDefault();
    const entry = { ...rule, ticker: rule.ticker.toUpperCase(), currency: rule.currency.toUpperCase() };
    if (canonicalPrice(entry.target) === "0.") {
      setMessage("Enter a target price greater than zero.");
      return;
    }
    if (preferences.stock_alerts.some((item) => item.ticker === entry.ticker && item.currency === entry.currency &&
        item.direction === entry.direction && canonicalPrice(item.target) === canonicalPrice(entry.target))) {
      setMessage("This price rule is already on the list.");
      return;
    }
    setPreferences({ ...preferences, stock_alerts: [...preferences.stock_alerts, entry] });
    setRule(emptyRule);
    setMessage("Price rule added to your changes. Save settings to apply it.");
  }

  return <main className="notification-page">
    <header className="notification-page-header">
      <div>
        <Link to="/notifications" className="notification-back"><FiArrowLeft aria-hidden="true" /> Notifications</Link>
        <h1><FiSettings aria-hidden="true" /> Notification settings</h1>
        <p>Choose which alerts appear in your FinDash inbox.</p>
      </div>
    </header>
    {loadError ? <div className="notification-panel notification-callout" role="status">
      <p>Could not load notification settings.</p>
      <button type="button" className="notification-secondary" onClick={() => { setLoadError(false); setAttempt(attempt + 1); }}>Retry</button>
    </div> : !preferences ? <div className="notification-panel notification-loading" role="status">Loading settings…</div> : <>
      <fieldset className="notification-panel notification-settings" disabled={saving}>
        <legend>Alert categories</legend>
        {Object.entries(categories).map(([key, item]) => <label key={key} className="notification-toggle">
          <span><strong>{item.label}</strong><small id={`notification-help-${key}`}>{item.description}</small></span>
          <input type="checkbox" checked={Boolean(preferences.categories[key])} aria-label={item.label}
            aria-describedby={`notification-help-${key}`}
            onChange={(event) => setPreferences({
              ...preferences, categories: { ...preferences.categories, [key]: event.target.checked },
            })} />
        </label>)}
      </fieldset>
      <section className="notification-panel notification-stock-settings" aria-labelledby="notification-stock-heading">
        <h2 id="notification-stock-heading">Stock price rules</h2>
        <p>Use a ticker from your watchlist and the quote’s currency. FinDash checks these rules when market checks are enabled.</p>
        {preferences.stock_alerts.length ? <ul className="notification-stock-rules">
          {preferences.stock_alerts.map((item, index) => <li key={`${item.ticker}:${item.currency}:${item.direction}:${item.target}`}>
            <span><strong>{item.ticker}</strong> · {item.direction === "above" ? "At or above" : "At or below"} {item.target} {item.currency}</span>
            <button type="button" disabled={saving} className="notification-secondary" onClick={() => setPreferences({
              ...preferences, stock_alerts: preferences.stock_alerts.filter((_, position) => position !== index),
            })}>Remove<span className="notification-visually-hidden"> {item.ticker} price rule</span></button>
          </li>)}
        </ul> : <p>No price rules configured.</p>}
        <form onSubmit={addRule}>
          <fieldset className="notification-rule-fields" disabled={saving || preferences.stock_alerts.length >= 10}>
            <legend className="notification-visually-hidden">Add stock price rule</legend>
            <label>Ticker<input required maxLength={10} pattern="[A-Za-z0-9]+(?:[.\\-][A-Za-z0-9]+)*" value={rule.ticker}
              onChange={(event) => setRule({ ...rule, ticker: event.target.value })} /></label>
            <label>Currency<input required maxLength={3} pattern="[A-Za-z]{3}" value={rule.currency}
              onChange={(event) => setRule({ ...rule, currency: event.target.value })} /></label>
            <label>Condition<select value={rule.direction} onChange={(event) => setRule({ ...rule, direction: event.target.value })}>
              <option value="above">At or above</option><option value="below">At or below</option>
            </select></label>
            <label>Target price<input required inputMode="decimal" type="text" pattern="[0-9]{1,10}([.][0-9]{1,8})?" maxLength={19} value={rule.target}
              onChange={(event) => setRule({ ...rule, target: event.target.value })} /></label>
            <button className="notification-secondary" type="submit">Add rule</button>
          </fieldset>
        </form>
      </section>
      <div className="notification-settings-footer">
        <button className="notification-primary" type="button" disabled={saving || !dirty} onClick={save}>{saving ? "Saving…" : "Save settings"}</button>
        <p className="notification-feedback" role="status">{message}</p>
      </div>
    </>}
  </main>;
}
