import { useEffect, useId, useRef, useState } from "react";
import PropTypes from "prop-types";
import { Link, useParams } from "react-router-dom";
import { FiArrowLeft, FiRotateCcw, FiSliders } from "react-icons/fi";
import api from "../api";
import GoalScenarioComparison from "../components/goals/GoalScenarioComparison";
import { goalEndpoint, goalError } from "../financialGoals";
import { blankScenario, scenarioChanges, scenarioDraft, sliderScale } from "../goalScenarios";
import "../styles/pages/FinancialGoals.css";
import "../styles/pages/GoalScenario.css";

const timeout = 12_000;

function SavingsInput({ label, currency, field, draft, change, reference = 0, slider = false, error }) {
  const id = useId();
  const amount = Number(draft.replace(",", "."));
  const value = draft === "" || !Number.isFinite(amount) || amount < 0 ? reference : amount;
  const scale = sliderScale(value, reference);
  return <div className="goals-scenario-field">
    <label htmlFor={id}>{label} <span className="goals-muted">({currency})</span></label>
    <input id={id} name={field} inputMode="decimal" maxLength={15} value={draft} placeholder={String(reference)}
      aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-error` : undefined}
      onChange={(event) => change(field, event.target.value)} />
    {slider && <input type="range" aria-label={`${label} slider`} {...scale}
      onChange={(event) => change(field, event.target.value)} />}
    {error && <p id={`${id}-error`} className="goals-error">{error}</p>}
  </div>;
}

SavingsInput.propTypes = {
  label: PropTypes.string.isRequired, currency: PropTypes.string.isRequired, field: PropTypes.string.isRequired,
  draft: PropTypes.string.isRequired, change: PropTypes.func.isRequired, reference: PropTypes.number,
  slider: PropTypes.bool, error: PropTypes.string,
};

export default function GoalScenario() {
  const { id } = useParams();
  return <GoalScenarioScreen key={id} id={id} />;
}

function GoalScenarioScreen({ id }) {
  const url = goalEndpoint(id);
  const endpoint = `${url}scenarios/`;
  const [goal, setGoal] = useState(null);
  const [goalErrorText, setGoalErrorText] = useState("");
  const [saved, setSaved] = useState(null);
  const [savedError, setSavedError] = useState("");
  const [draft, setDraft] = useState(blankScenario);
  const [name, setName] = useState("");
  const [preview, setPreview] = useState(null);
  const [previewReload, setPreviewReload] = useState(0);
  const [reload, setReload] = useState(0);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const requestLock = useRef(false);
  const { changes, errors } = scenarioChanges(draft);
  const payload = Object.keys(errors).length ? null : JSON.stringify({ changes });

  useEffect(() => {
    const controller = new AbortController();
    const config = { signal: controller.signal, timeout };
    api.get(url, config).then(({ data }) => {
      if (!controller.signal.aborted) setGoal(data);
    }).catch((error) => {
      if (!controller.signal.aborted) setGoalErrorText(goalError(error, "Could not load this goal."));
    });
    api.get(endpoint, config).then(({ data }) => {
      if (!controller.signal.aborted) setSaved(data);
    }).catch((error) => {
      if (!controller.signal.aborted) setSavedError(goalError(error, "Could not load saved scenarios."));
    });
    return () => controller.abort();
  }, [url, endpoint, reload]);

  useEffect(() => {
    if (!goal || payload === null) return;
    const controller = new AbortController();
    const pending = setTimeout(() => {
      api.post(`${endpoint}preview/`, JSON.parse(payload), { signal: controller.signal, timeout }).then(({ data }) => {
        if (!controller.signal.aborted) setPreview({ payload, data });
      }).catch((error) => {
        if (!controller.signal.aborted) setPreview({ payload, error: goalError(error, "Could not recalculate the estimate.") });
      });
    }, 150);
    return () => { clearTimeout(pending); controller.abort(); };
  }, [endpoint, goal, payload, previewReload]);

  function change(field, value) {
    setDraft((previous) => ({ ...previous, [field]: value }));
  }

  function reset() {
    setDraft(blankScenario);
    setName("");
    setNotice("");
  }

  async function save(event) {
    event.preventDefault();
    if (requestLock.current || !name.trim() || !Object.keys(changes).length || payload === null) return;
    requestLock.current = true;
    setBusy(true);
    setNotice("");
    try {
      const { data } = await api.post(endpoint, { name: name.trim(), changes }, { timeout });
      setSaved((previous) => [data, ...(previous || [])]);
      setName("");
      setNotice(`Saved “${data.name}”.`);
    } catch (error) {
      setNotice(goalError(error, "Could not save this scenario."));
    } finally {
      requestLock.current = false;
      setBusy(false);
    }
  }

  async function remove(item) {
    if (requestLock.current) return;
    requestLock.current = true;
    setBusy(true);
    setNotice("");
    try {
      await api.delete(`${endpoint}${item.id}/`, { timeout });
      setSaved((previous) => previous.filter((row) => row.id !== item.id));
      setNotice(`Removed “${item.name}”.`);
    } catch (error) {
      setNotice(goalError(error, "Could not remove this scenario."));
    } finally {
      requestLock.current = false;
      setBusy(false);
    }
  }

  function reloadData() {
    setGoalErrorText("");
    setSavedError("");
    setReload((value) => value + 1);
  }

  const current = preview?.payload === payload ? preview : null;

  return <main className="goals-page goal-scenario-page">
    <Link className="goals-scenario-back" to="/goals"><FiArrowLeft aria-hidden="true" /> Financial Goals</Link>
    <header className="goals-page-header">
      <div className="goals-page-title">
        <span className="goals-symbol"><FiSliders aria-hidden="true" /></span>
        <div><h1>Goal scenario simulator</h1>{goal && <p>{goal.name} · {goal.currency}</p>}</div>
      </div>
    </header>
    {goalErrorText ? <div className="goals-callout">
      <p role="alert">{goalErrorText}</p><button type="button" onClick={reloadData}>Retry</button>
    </div> : !goal ? <p className="goals-callout" role="status">Loading goal…</p> : <div className="goals-scenario-layout">
      <div className="goals-scenario-stack">
        <section className="goals-card" aria-label="Hypothetical changes">
          <div className="goals-scenario-controls-heading">
            <h2>Hypothetical changes</h2>
            <button type="button" onClick={reset}><FiRotateCcw aria-hidden="true" /> Reset</button>
          </div>
          <p className="goals-muted">Blank fields use the saved goal plan. Extra savings are optional. Simulations leave the goal ledger unchanged.</p>
          <SavingsInput label="Monthly contribution" currency={goal.currency} field="monthly_contribution"
            draft={draft.monthly_contribution} reference={Number(goal.monthly_contribution || 0)} change={change}
            error={errors.monthly_contribution} slider />
          <SavingsInput label="One-time contribution" currency={goal.currency} field="one_time_contribution"
            draft={draft.one_time_contribution} change={change} error={errors.one_time_contribution} />
          <SavingsInput label="Monthly expense reduction" currency={goal.currency} field="expense_reduction"
            draft={draft.expense_reduction} change={change} error={errors.expense_reduction} slider />
          <SavingsInput label="Target amount" currency={goal.currency} field="target_amount" draft={draft.target_amount}
            reference={Number(goal.target_amount)} change={change} error={errors.target_amount} />
          <label className="goals-scenario-field">Target date treatment
            <select value={draft.dateMode} onChange={(event) => change("dateMode", event.target.value)}>
              <option value="saved">Use saved date</option>
              <option value="custom">Change the date</option>
              <option value="clear">Remove the date</option>
            </select>
          </label>
          {draft.dateMode === "custom" && <label className="goals-scenario-field">Scenario target date
            <input type="date" max="9999-12-31" value={draft.target_date} aria-invalid={Boolean(errors.target_date)}
              onChange={(event) => change("target_date", event.target.value)} />
            {errors.target_date && <span className="goals-error">{errors.target_date}</span>}
          </label>}
        </section>
        <section className="goals-card" aria-label="Saved goal scenarios">
          <h2>Saved scenarios</h2>
          <form className="goals-scenario-save" onSubmit={save}>
            <label className="goals-scenario-field">Scenario name
              <input maxLength={80} required value={name} onChange={(event) => setName(event.target.value)} />
            </label>
            <button type="submit" className="goals-primary" disabled={busy || !payload || !Object.keys(changes).length}>Save scenario</button>
          </form>
          <p className="goals-muted" role="status">{notice}</p>
          {savedError ? <div><p role="alert">{savedError}</p><button type="button" onClick={reloadData}>Retry list</button></div> :
            saved === null ? <p className="goals-muted">Loading saved scenarios…</p> :
            saved.length === 0 ? <p className="goals-muted">No scenarios saved for this goal.</p> :
            <ul className="goals-scenario-saved">{saved.map((item) => <li key={item.id}>
              <strong>{item.name}</strong>
              <div className="goals-actions">
                <button type="button" disabled={busy} aria-label={`Load ${item.name}`} onClick={() => {
                  setDraft(scenarioDraft(item.changes)); setName(""); setNotice(`Loaded “${item.name}”.`);
                }}>Load</button>
                <button type="button" disabled={busy} aria-label={`Remove ${item.name}`} onClick={() => remove(item)}>Remove</button>
              </div>
            </li>)}</ul>}
        </section>
      </div>
      <div className="goals-scenario-stack">
        {!payload ? <p className="goals-callout" role="status">Correct the highlighted fields to update the comparison.</p> :
          current?.error ? <div className="goals-callout">
            <p role="alert">{current.error}</p>
            <button type="button" onClick={() => { setPreview(null); setPreviewReload((value) => value + 1); }}>Retry estimate</button>
          </div> : !current?.data && <p className="goals-callout" role="status">Updating the comparison…</p>}
        {preview?.data && <div className="goals-scenario-stack" role="group" aria-label={current ? "Latest estimate" : "Previous estimate"}>
          <GoalScenarioComparison result={preview.data} />
        </div>}
      </div>
    </div>}
  </main>;
}

GoalScenarioScreen.propTypes = { id: PropTypes.string.isRequired };
