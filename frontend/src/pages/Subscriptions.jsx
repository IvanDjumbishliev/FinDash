import { useEffect, useRef, useState } from "react";
import { jwtDecode } from "jwt-decode";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import api from "../api";
import SubscriptionEditor from "../components/SubscriptionEditor";
import { ACCESS_TOKEN } from "../constants";
import {
  billingCycles, combineSubscriptions, filterSubscriptions, formatDate, formatMoney,
  statuses, subscriptionOverview, subscriptionStatus,
} from "../subscriptions";
import "../styles/pages/Subscriptions.css";

const endpoint = "/api/subscriptions/";

function storageKey() {
  try {
    const owner = jwtDecode(localStorage.getItem(ACCESS_TOKEN)).user_id;
    if (typeof owner === "number" || typeof owner === "string") {
      return `findash.subscriptions:${api.defaults.baseURL || window.location.origin}:${owner}`;
    }
  } catch {
    // Local tracking requires an identifiable signed-in account.
  }
  return null;
}

function loadLocal(key) {
  try {
    const saved = key && JSON.parse(localStorage.getItem(key));
    if (Array.isArray(saved?.manual) && saved.preferences) return saved;
  } catch {
    // The server watchlist remains available when browser storage is blocked.
  }
  return { manual: [], preferences: {} };
}

function errorMessage(error, fallback) {
  const data = error.response?.data;
  if (typeof data?.detail === "string") return data.detail;
  if (typeof data?.error === "string") return data.error;
  return fallback;
}

export default function Subscriptions() {
  const [key] = useState(storageKey);
  const [local, setLocal] = useState(() => loadLocal(key));
  const [server, setServer] = useState([]);
  const [filter, setFilter] = useState("all");
  const [sort, setSort] = useState("renewal");
  const [chartCurrency, setChartCurrency] = useState("");
  const [editor, setEditor] = useState(null);
  const [editorError, setEditorError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useState("");
  const [reload, setReload] = useState(0);
  const editorOpener = useRef(null);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      setLoading(true);
      setLoadError("");
      try {
        const { data } = await api.get(endpoint, { signal: controller.signal, timeout: 15000 });
        if (!Array.isArray(data)) throw new Error("Unexpected subscription response");
        if (!controller.signal.aborted) setServer(data);
      } catch (error) {
        if (!controller.signal.aborted) {
          setLoadError(errorMessage(error, "Could not load saved subscriptions."));
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    load();
    return () => controller.abort();
  }, [reload]);

  function saveLocal(next) {
    if (!key) throw new Error("Sign in again to save changes in this browser.");
    try {
      localStorage.setItem(key, JSON.stringify(next));
    } catch {
      throw new Error("Browser storage is unavailable. Changes on this device could not be saved.");
    }
    setLocal(next);
  }

  function closeEditor() {
    setEditor(null);
    setEditorError("");
    requestAnimationFrame(() => editorOpener.current?.focus());
  }

  function openEditor(event, record) {
    editorOpener.current = event.currentTarget;
    setEditor({ record });
    setEditorError("");
    setNotice("");
  }

  function replaceServer(record) {
    setServer((previous) => previous.map((item) => item.id === record.id ? record : item));
  }

  async function runAction(label, task, onError = setActionError) {
    setBusy(label);
    setActionError("");
    setEditorError("");
    setNotice("");
    try {
      await task();
    } catch (error) {
      onError(errorMessage(error, error.message && !error.isAxiosError
        ? error.message : "Could not complete this subscription action. Try again."));
    } finally {
      setBusy("");
    }
  }

  function detect() {
    return runAction("detect", async () => {
      const { data } = await api.post(`${endpoint}detect/`, undefined, { timeout: 30000 });
      if (!Array.isArray(data)) throw new Error("Could not read scan results.");
      setServer((previous) => {
        const records = new Map(previous.map((record) => [record.id, record]));
        for (const record of data) records.set(record.id, record);
        return [...records.values()];
      });
      const count = data.filter(({ status }) => status === "candidate").length;
      setNotice(count ? `${count} unconfirmed ${count === 1 ? "match" : "matches"} to review.` : "No unconfirmed matches in this scan.");
    });
  }

  function confirm(record) {
    return runAction("confirm", async () => {
      const { data } = await api.patch(`${endpoint}${record.id}/`, { status: "confirmed" });
      replaceServer(data);
      setNotice(`${data.merchant} confirmed.`);
    });
  }

  function save(edit) {
    return runAction("save", async () => {
      const record = editor.record;
      if (edit.manual) {
        saveLocal({
          ...local,
          manual: [...local.manual.filter(({ id }) => id !== edit.manual.id), edit.manual],
        });
      } else {
        const fieldsChanged = Object.entries(edit.patch).some(
          ([field, value]) => record[field] !== value
        );
        const preferencesChanged = edit.preferences.category !== (record.category || "Uncategorized")
          || edit.preferences.tracking_status !== (record.tracking_status || "active");
        if (fieldsChanged) {
          const { data } = await api.patch(`${endpoint}${record.id}/`, edit.patch);
          replaceServer(data);
        }
        if (preferencesChanged) {
          saveLocal({ ...local, preferences: { ...local.preferences, [record.id]: edit.preferences } });
        }
      }
      closeEditor();
      setNotice("Subscription saved.");
    }, setEditorError);
  }

  function remove(record) {
    const message = record.local
      ? `Remove ${record.merchant} from this browser?`
      : `Remove ${record.merchant} from FinDash? A later scan may find it again.`;
    if (!window.confirm(message)) return;
    return runAction("remove", async () => {
      if (record.local) {
        saveLocal({ ...local, manual: local.manual.filter(({ id }) => id !== record.id) });
      } else {
        await api.delete(`${endpoint}${record.id}/`);
        setServer((previous) => previous.filter(({ id }) => id !== record.id));
        if (Object.hasOwn(local.preferences, record.id)) {
          const preferences = { ...local.preferences };
          delete preferences[record.id];
          saveLocal({ ...local, preferences });
        }
      }
      setNotice("Subscription removed.");
    });
  }

  const records = combineSubscriptions(server, local);
  const overview = subscriptionOverview(records);
  const displayed = filterSubscriptions(records, filter, sort);
  const currency = Object.hasOwn(overview.breakdown, chartCurrency)
    ? chartCurrency : overview.totals[0]?.currency;
  const waiting = loading || Boolean(busy);

  return (
    <main className="dashboard-shell subscriptions-page">
      <header className="subscription-heading">
        <div>
          <h1>Subscriptions</h1>
          <p>Review recurring payments and plan for renewals.</p>
        </div>
        <div className="subscription-actions">
          <button type="button" disabled={waiting || Boolean(editor)} onClick={detect}>{busy === "detect" ? "Scanning…" : "Detect subscriptions"}</button>
          <button type="button" className="subscription-primary" disabled={waiting || Boolean(editor)} onClick={(event) => openEditor(event)}>Add subscription</button>
        </div>
      </header>

      <p className="subscription-note">Manual entries, categories, and pause or cancel labels are saved in this browser. These labels only affect tracking in FinDash.</p>
      {loading && <p role="status" className="subscription-message">Loading subscriptions…</p>}
      {loadError && (
        <div className="subscription-message">
          <p role="alert">{loadError} Totals may be incomplete.</p>
          <button type="button" disabled={waiting} onClick={() => setReload((number) => number + 1)}>Retry</button>
        </div>
      )}
      {actionError && <p role="alert" className="subscription-message">{actionError}</p>}
      {notice && <p role="status" className="subscription-message">{notice}</p>}

      {editor && (
        <SubscriptionEditor
          key={editor.record?.id ?? "new"}
          record={editor.record}
          onSave={save}
          onClose={closeEditor}
          busy={Boolean(busy)}
          error={editorError}
        />
      )}

      <section aria-label="Subscription overview" aria-busy={loading}>
        {loading ? (
          <div className="subscription-metrics" aria-hidden="true">
            {[1, 2, 3].map((item) => <div key={item} className="subscription-panel subscription-skeleton" />)}
          </div>
        ) : (
          <>
            <div className="subscription-metrics">
              {[
                ["monthly", "Estimated monthly spending"],
                ["annual", "Estimated annual spending"],
              ].map(([period, title]) => (
                <div className="subscription-panel" key={period}>
                  <h2>{title}</h2>
                  {overview.totals.length
                    ? overview.totals.map((total) => (
                      <p className="subscription-total" key={total.currency}>
                        {formatMoney(total[period], total.currency)} <small>{total.currency}</small>
                      </p>
                    ))
                    : <p className="subscription-total">—</p>}
                </div>
              ))}
              <div className="subscription-panel">
                <h2>Active subscriptions</h2>
                <p className="subscription-total">{overview.activeCount}</p>
              </div>
            </div>
            <p className="subscription-note">Estimates include active, confirmed and manually added subscriptions. Amounts are grouped by currency.</p>

            <div className="subscription-overview">
              <section className="subscription-panel" aria-labelledby="subscription-upcoming">
                <h2 id="subscription-upcoming">Upcoming renewals</h2>
                <p className="subscription-note">Next 30 days</p>
                {overview.upcoming.length ? (
                  <ul className="subscription-renewals">
                    {overview.upcoming.map((record) => (
                      <li key={record.id}>
                        <div>
                          <strong>{record.merchant}</strong>
                          <div className="subscription-note">{record.status === "candidate" ? "Predicted" : "Confirmed"}</div>
                        </div>
                        <div>
                          <time dateTime={record.next_expected_payment}>{formatDate(record.next_expected_payment)}</time>
                          <div>{formatMoney(record.estimated_amount, record.currency)}</div>
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : <p>No renewals expected in the next 30 days.</p>}
              </section>

              <section className="subscription-panel" aria-labelledby="subscription-category-chart">
                <h2 id="subscription-category-chart">Monthly spending by category</h2>
                {currency ? (
                  <>
                    {overview.totals.length > 1 && (
                      <label className="subscription-chart-currency">Chart currency
                        <select value={currency} onChange={(event) => setChartCurrency(event.target.value)}>
                          {overview.totals.map((total) => <option key={total.currency}>{total.currency}</option>)}
                        </select>
                      </label>
                    )}
                    <div className="subscription-chart">
                      <ResponsiveContainer width="100%" height={Math.max(170, overview.breakdown[currency].length * 38 + 36)}>
                        <BarChart layout="vertical" data={overview.breakdown[currency]} margin={{ right: 10 }}>
                          <CartesianGrid horizontal={false} stroke="var(--border-subtle)" />
                          <XAxis type="number" tick={{ fill: "var(--muted)", fontSize: 11 }} />
                          <YAxis type="category" dataKey="category" width={100} tick={{ fill: "var(--muted)", fontSize: 11 }} />
                          <Tooltip formatter={(value) => [formatMoney(value, currency), "Monthly estimate"]}
                            contentStyle={{ background: "var(--surface)", color: "var(--ink)", borderColor: "var(--border-color)" }} />
                          <Bar dataKey="monthly" name="Monthly estimate" fill="var(--primary-color)" radius={[0, 4, 4, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                    <details>
                      <summary>View category amounts</summary>
                      <ul className="subscription-renewals">
                        {overview.breakdown[currency].map(({ category, monthly }) => (
                          <li key={category}><span>{category}</span><span>{formatMoney(monthly, currency)}</span></li>
                        ))}
                      </ul>
                    </details>
                  </>
                ) : <p>Confirm or add a subscription to see the spending breakdown.</p>}
              </section>
            </div>
          </>
        )}
      </section>

      <section aria-labelledby="subscription-list-title">
        <div className="subscription-heading subscription-list-heading">
          <h2 id="subscription-list-title">Your subscriptions</h2>
          <div className="subscription-actions subscription-controls">
            <label>Filter
              <select value={filter} onChange={(event) => setFilter(event.target.value)}>
                <option value="all">All statuses</option>
                {Object.entries(statuses).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
            <label>Sort by
              <select value={sort} onChange={(event) => setSort(event.target.value)}>
                <option value="renewal">Upcoming renewal</option>
                <option value="price">Price within currency</option>
              </select>
            </label>
          </div>
        </div>
        {!loading && !displayed.length && (
          <p className="subscription-message">
            {records.length ? "No subscriptions match this filter."
              : loadError ? "No subscriptions are available to display."
                : "No subscriptions yet. Scan your transactions or add one manually."}
          </p>
        )}
        <ul className="subscription-cards">
          {displayed.map((record) => {
            const predicted = record.status === "candidate";
            return (
              <li className="subscription-panel subscription-card" key={record.id}>
                <div className="subscription-card-top">
                  <div>
                    <h3>{record.merchant}</h3>
                    <p className="subscription-note">{record.category || "Uncategorized"}</p>
                  </div>
                  <span className="subscription-badge" data-status={subscriptionStatus(record)}>
                    {statuses[subscriptionStatus(record)]}
                  </span>
                </div>
                <p className="subscription-card-price">
                  <strong>{formatMoney(record.estimated_amount, record.currency)}</strong>
                  <span>{billingCycles[record.billing_frequency].label}</span>
                </p>
                <p>Next payment <time dateTime={record.next_expected_payment}>{formatDate(record.next_expected_payment)}</time></p>
                <p className="subscription-note">
                  {predicted ? `Predicted · ${Math.round(Number(record.detection_confidence) * 100)}% confidence`
                    : record.local ? "Manual · This browser" : "Confirmed"}
                </p>
                <div className="subscription-actions">
                  {predicted && <button type="button" className="subscription-primary" disabled={waiting || Boolean(editor)} onClick={() => confirm(record)}>Confirm</button>}
                  <button type="button" disabled={waiting || Boolean(editor)} onClick={(event) => openEditor(event, record)}>Edit</button>
                  <button type="button" disabled={waiting || Boolean(editor)} onClick={() => remove(record)}>Remove</button>
                </div>
              </li>
            );
          })}
        </ul>
      </section>
    </main>
  );
}
