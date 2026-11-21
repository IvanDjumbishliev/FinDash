import { useEffect, useState } from "react";
import PropTypes from "prop-types";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import api from "../api";
import { balanceInput } from "../cashFlowForecast";
import { displayDate, money } from "../copilotPresentation";

const endpoint = "/api/forecast/cash-flow/scenarios/";
const initial = {
  income: "", incomeDay: "1", category: "", percent: "", expense: "", expenseDay: "1",
  frequency: "monthly", subscription: "", purchase: "", purchaseDay: "1", balance: "",
};

function changesFrom(draft) {
  const amount = (value) => value.trim().replace(",", ".");
  return {
    ...(draft.income && { monthly_income: { amount: amount(draft.income), day: draft.incomeDay } }),
    ...(draft.category && { spending_reduction: { category: draft.category, percent: draft.percent } }),
    ...(draft.expense && { recurring_expense: { amount: amount(draft.expense), day: draft.expenseDay, frequency: draft.frequency } }),
    ...(draft.subscription && { remove_subscription_id: draft.subscription }),
    ...(draft.purchase && { purchase: { amount: amount(draft.purchase), day: draft.purchaseDay } }),
    ...(draft.balance && { starting_balance: balanceInput(draft.balance).value ?? amount(draft.balance) }),
  };
}

function draftFrom(changes) {
  return {
    ...initial,
    income: changes.monthly_income?.amount ?? "", incomeDay: String(changes.monthly_income?.day ?? 1),
    category: changes.spending_reduction?.category ?? "", percent: String(changes.spending_reduction?.percent ?? ""),
    expense: changes.recurring_expense?.amount ?? "", expenseDay: String(changes.recurring_expense?.day ?? 1),
    frequency: changes.recurring_expense?.frequency ?? "monthly",
    subscription: String(changes.remove_subscription_id ?? ""),
    purchase: changes.purchase?.amount ?? "", purchaseDay: String(changes.purchase?.day ?? 1),
    balance: changes.starting_balance ?? "",
  };
}

function messages(value) {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(messages);
  if (value && typeof value === "object") return Object.entries(value).flatMap(([key, entry]) =>
    messages(entry).map((text) => key === "error" ? text : `${key.replaceAll("_", " ")}: ${text}`));
  return [];
}

function failureText(error, fallback) {
  return messages(error.response?.data).join(" ") || fallback;
}

function ScenarioComparison({ comparison }) {
  const { totals, currency } = comparison;
  const balance = totals.balance_difference != null;
  const rows = comparison.days.map((point) => ({
    date: point.date,
    baseline: Number(balance ? point.baseline_balance : point.baseline_net_cash_flow),
    scenario: Number(balance ? point.scenario_balance : point.scenario_net_cash_flow),
  }));
  const value = (amount) => amount == null ? "Unavailable" : money(amount, currency);
  return <section className="forecast-scenario-comparison" aria-label="Baseline and hypothetical scenario comparison">
    <h3>{balance ? "Projected balance comparison" : "Cumulative cash flow comparison"}</h3>
    {comparison.status !== "estimated" && <p className="forecast-muted">Scheduled flows only because recorded history is limited.</p>}
    <dl className="forecast-kpis">
      <div><dt>Baseline ending balance</dt><dd>{value(totals.baseline_balance)}</dd></div>
      <div><dt>Hypothetical ending balance</dt><dd>{value(totals.scenario_balance)}</dd></div>
      <div><dt>Ending balance difference</dt><dd>{value(totals.balance_difference)}</dd>
        {!balance && <dd>Apply a baseline starting balance to compare balances.</dd>}</div>
      <div><dt>Net cash flow difference</dt><dd>{value(totals.net_cash_flow_difference)}</dd></div>
    </dl>
    {comparison.notes.length > 0 && <ul className="forecast-muted">{comparison.notes.map((note) => <li key={note}>{note}</li>)}</ul>}
    <div className="forecast-scenario-legend"><span>Baseline</span><span>Hypothetical scenario</span></div>
    <div aria-hidden="true">
      <ResponsiveContainer width="100%" height={235} minWidth={0}>
        <LineChart data={rows} accessibilityLayer={false} margin={{ left: 4, right: 12, top: 6 }}>
          <CartesianGrid vertical={false} stroke="var(--border-subtle)" />
          <XAxis dataKey="date" tickFormatter={(day) => day.slice(5)} minTickGap={26} tick={{ fill: "var(--muted)", fontSize: 11 }} />
          <YAxis domain={["auto", "auto"]} width={51} tick={{ fill: "var(--muted)", fontSize: 11 }} />
          <Tooltip labelFormatter={displayDate} formatter={(amount) => value(amount)}
            contentStyle={{ background: "var(--surface)", borderColor: "var(--border-color)" }} />
          <Line dataKey="baseline" name="Baseline" stroke="var(--forecast-actual)" strokeWidth={2} dot={false} isAnimationActive={false} />
          <Line dataKey="scenario" name="Hypothetical scenario" stroke="var(--forecast-projected)" strokeWidth={2.5}
            strokeDasharray="6 4" dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
    <details className="forecast-chart-data"><summary>View scenario comparison data</summary>
      <div className="forecast-table-scroll" tabIndex={0} role="region" aria-label="Scenario comparison data">
        <table><thead><tr><th>Date</th><th>Baseline</th><th>Hypothetical</th><th>Difference</th></tr></thead>
          <tbody>{comparison.days.map((day) => <tr key={day.date}>
            <th scope="row">{displayDate(day.date)}</th>
            <td>{value(balance ? day.baseline_balance : day.baseline_net_cash_flow)}</td>
            <td>{value(balance ? day.scenario_balance : day.scenario_net_cash_flow)}</td>
            <td>{value(balance ? day.balance_difference : day.net_cash_flow_difference)}</td>
          </tr>)}</tbody>
        </table>
      </div>
    </details>
  </section>;
}

ScenarioComparison.propTypes = {
  comparison: PropTypes.shape({
    totals: PropTypes.object.isRequired, currency: PropTypes.string.isRequired, status: PropTypes.string.isRequired,
    days: PropTypes.array.isRequired, notes: PropTypes.arrayOf(PropTypes.string).isRequired,
  }).isRequired,
};

export default function ForecastScenarios({ data, onHorizonChange }) {
  const [draft, setDraft] = useState(initial);
  const [applied, setApplied] = useState(null);
  const [live, setLive] = useState(false);
  const [comparison, setComparison] = useState(null);
  const [name, setName] = useState("");
  const [saved, setSaved] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [savedError, setSavedError] = useState("");
  const [status, setStatus] = useState("");
  const [version, setVersion] = useState(0);
  const [savedVersion, setSavedVersion] = useState(0);
  const currency = data?.currency;
  const startingBalance = data?.starting_balance;
  const horizon = data?.horizon_days;
  const categories = Object.keys(data?.scenario_options?.weekly_variable_expenses_by_category ?? {});
  const subscriptions = (data?.recurring ?? []).filter((item) => item.subscription_id != null);
  const changes = changesFrom(draft);
  const hasChanges = Object.keys(changes).length > 0;

  useEffect(() => {
    const controller = new AbortController();
    api.get(endpoint, { signal: controller.signal }).then(({ data: records }) => {
      if (!controller.signal.aborted) setSaved(records);
    }).catch(() => {
      if (!controller.signal.aborted) setSavedError("Couldn’t load saved scenarios.");
    });
    return () => controller.abort();
  }, [savedVersion]);

  useEffect(() => {
    if (!applied || !currency || !horizon) return;
    const controller = new AbortController();
    api.post(`${endpoint}preview/`, {
      horizon, currency, ...(startingBalance != null && { starting_balance: startingBalance }), changes: applied,
    }, { signal: controller.signal }).then(({ data: result }) => {
      if (!controller.signal.aborted) setComparison({ result, applied, horizon, startingBalance, currency, version });
    }).catch((failure) => {
      if (!controller.signal.aborted) setComparison({
        applied, horizon, startingBalance, currency, version,
        error: failureText(failure, "Couldn’t compare the scenario. Try again."),
      });
    });
    return () => controller.abort();
  }, [applied, currency, horizon, startingBalance, version]);

  useEffect(() => {
    if (!live || applied) return;
    const next = changesFrom(draft);
    if (!Object.keys(next).length) return;
    const timer = setTimeout(() => setApplied(next), 450);
    return () => clearTimeout(timer);
  }, [applied, draft, live]);

  function edit(key, value) {
    setDraft((previous) => ({ ...previous, [key]: value }));
    setApplied(null);
    setError("");
    setStatus("");
  }

  function reset() {
    setDraft(initial);
    setLive(false);
    setApplied(null);
    setComparison(null);
    setName("");
    setError("");
    setStatus("Scenario inputs reset.");
  }

  async function save(event) {
    event.preventDefault();
    if (!hasChanges || !name.trim() || !currency) return;
    setSaving(true);
    setError("");
    setStatus("");
    try {
      const { data: record } = await api.post(endpoint, { name: name.trim(), horizon, currency, changes });
      setSaved((previous) => [record, ...(previous ?? [])]);
      setName("");
      setStatus(`Saved ${record.name}.`);
    } catch (failure) {
      setError(failureText(failure, "Couldn’t save this scenario."));
    } finally {
      setSaving(false);
    }
  }

  async function remove(record) {
    setSaving(true);
    setSavedError("");
    try {
      await api.delete(`${endpoint}${record.id}/`);
      setSaved((previous) => previous.filter((item) => item.id !== record.id));
      setStatus(`Deleted ${record.name}.`);
    } catch {
      setSavedError("Couldn’t delete this scenario.");
    } finally {
      setSaving(false);
    }
  }

  function load(record) {
    if (record.currency !== currency) {
      setSavedError(`This scenario uses ${record.currency}. The current forecast uses ${currency}.`);
      return;
    }
    setDraft(draftFrom(record.changes));
    setLive(true);
    setApplied(record.changes);
    onHorizonChange(record.horizon);
    setError("");
    setSavedError("");
    setStatus(`Loaded ${record.name}.`);
  }

  const current = comparison?.applied === applied && comparison?.horizon === horizon &&
    comparison.currency === currency && comparison.startingBalance === startingBalance && comparison.version === version
    ? comparison : null;
  const field = (key, label, inputMode = "decimal", type = "text") => <label>{label}
    <input type={type} inputMode={inputMode} value={draft[key]} maxLength={16}
      {...(type === "number" && { min: 1, max: key === "percent" ? 100 : 90 })}
      onChange={(event) => edit(key, event.target.value)} /></label>;

  return <section className="forecast-panel forecast-scenarios" aria-labelledby="forecast-scenarios-title">
    <h2 id="forecast-scenarios-title">What-if scenarios</h2>
    <p className="forecast-muted">Explore hypothetical changes in {currency ?? "your forecast currency"}. Forecasts are estimates, and simulations leave your financial records untouched.</p>
    {!data && <p className="forecast-muted">Waiting for the baseline forecast…</p>}
    <form className="forecast-scenario-form" onSubmit={(event) => {
      event.preventDefault();
      if (hasChanges && currency) {
        setLive(true);
        setApplied(changes);
        setVersion((previous) => previous + 1);
      }
    }}>
      <p className="forecast-muted">Day 1 is the first forecast day. Recurring changes begin on the day you choose.</p>
      <div className="forecast-scenario-fields">
        <fieldset><legend>Increase monthly income</legend>
          {field("income", "Monthly increase")}{field("incomeDay", "Income start day", "numeric", "number")}
        </fieldset>
        <fieldset><legend>Reduce variable spending</legend>
          <label>Spending category<select value={draft.category} onChange={(event) => edit("category", event.target.value)}>
            <option value="">Choose category</option>
            {draft.category && !categories.includes(draft.category) && <option>{draft.category}</option>}
            {categories.map((category) => <option key={category}>{category}</option>)}
          </select></label>
          {field("percent", "Reduction (%)", "numeric", "number")}
          {!categories.length && <small>No category estimates are available for this baseline.</small>}
        </fieldset>
        <fieldset><legend>Add a recurring expense</legend>
          {field("expense", "Recurring amount")}{field("expenseDay", "Expense start day", "numeric", "number")}
          <label>Repeat<select value={draft.frequency} onChange={(event) => edit("frequency", event.target.value)}>
            <option value="monthly">Monthly</option><option value="weekly">Weekly</option>
          </select></label>
        </fieldset>
        <fieldset><legend>Exclude a subscription</legend>
          <label>Omit from this simulation<select value={draft.subscription} onChange={(event) => edit("subscription", event.target.value)}>
            <option value="">Keep all subscriptions</option>
            {draft.subscription && !subscriptions.some((item) => String(item.subscription_id) === draft.subscription) &&
              <option value={draft.subscription}>Previously selected subscription</option>}
            {subscriptions.map((item) => <option key={item.subscription_id} value={item.subscription_id}>
              {item.label} · {money(item.amount, currency)}
            </option>)}
          </select></label>
        </fieldset>
        <fieldset><legend>Add a one-time purchase</legend>
          {field("purchase", "Purchase amount")}{field("purchaseDay", "Purchase day", "numeric", "number")}
        </fieldset>
        <fieldset><legend>Change starting balance</legend>
          {field("balance", "Hypothetical starting balance")}
        </fieldset>
      </div>
      <div className="forecast-scenario-actions">
        <button type="submit" className="forecast-primary" disabled={!hasChanges || !currency}>Compare scenario</button>
        <button type="button" onClick={reset}>Reset scenario</button>
      </div>
    </form>

    {applied && !current && <p role="status">Calculating hypothetical forecast…</p>}
    {current?.error && <p className="forecast-error" role="alert">{current.error}</p>}
    {current?.result && <ScenarioComparison comparison={current.result} />}

    <div className="forecast-saved-scenarios">
      <h3>Saved scenarios</h3>
      <form className="forecast-scenario-actions" onSubmit={save}>
        <label>Scenario name<input value={name} maxLength={80} onChange={(event) => setName(event.target.value)} /></label>
        <button type="submit" disabled={!hasChanges || !name.trim() || saving || !currency}>Save scenario</button>
      </form>
      {error && <p className="forecast-error" role="alert">{error}</p>}
      {savedError && <div role="alert" className="forecast-error">{savedError} <button type="button" onClick={() => {
        setSavedError("");
        setSavedVersion((previous) => previous + 1);
      }}>Refresh saved scenarios</button></div>}
      <p role="status">{status}</p>
      {saved?.length > 0 ? <ul>{saved.map((record) => <li key={record.id}>
        <strong>{record.name}</strong> <small>{record.horizon} days · {record.currency}</small>
        <span><button type="button" onClick={() => load(record)} disabled={!currency}>Load {record.name}</button>
          <button type="button" onClick={() => remove(record)} disabled={saving}>Delete {record.name}</button></span>
      </li>)}</ul> : saved && <p className="forecast-muted">No scenarios saved yet.</p>}
    </div>
  </section>;
}

ForecastScenarios.propTypes = {
  data: PropTypes.shape({
    currency: PropTypes.string, starting_balance: PropTypes.string, horizon_days: PropTypes.number,
    scenario_options: PropTypes.shape({ weekly_variable_expenses_by_category: PropTypes.object }),
    recurring: PropTypes.array,
  }),
  onHorizonChange: PropTypes.func.isRequired,
};
