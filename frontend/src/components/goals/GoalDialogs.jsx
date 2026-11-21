import { useEffect, useId, useRef, useState } from "react";
import PropTypes from "prop-types";
import { FiX } from "react-icons/fi";
import api from "../../api";
import { requestId } from "../../requestId";
import { money } from "../../copilotPresentation";
import { blankGoal, goalDraft, goalEndpoint, goalError, ledgerDraft } from "../../financialGoals";

const goalShape = PropTypes.shape({
  id: PropTypes.number, name: PropTypes.string, currency: PropTypes.string, target_amount: PropTypes.string,
  archived: PropTypes.bool, target_date: PropTypes.string, monthly_contribution: PropTypes.string, current_amount: PropTypes.string,
});

export function GoalDialog({ title, children, onClose, busy = false }) {
  const id = useId();
  const dialog = useRef(null);
  useEffect(() => {
    const node = dialog.current;
    node.showModal();
    return () => node.close();
  }, []);

  return <dialog className="goals-dialog" ref={dialog} aria-labelledby={id} onCancel={(event) => {
    event.preventDefault();
    if (!busy) onClose();
  }}>
    <header className="goals-dialog-header">
      <h2 id={id}>{title}</h2>
      <button type="button" className="goals-icon-button" onClick={onClose} disabled={busy} aria-label="Close dialog">
        <FiX aria-hidden="true" />
      </button>
    </header>
    {children}
  </dialog>;
}

export function GoalEditor({ goal, onClose, onSave }) {
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState(() => goal ? {
    name: goal.name, target_amount: goal.target_amount, currency: goal.currency,
    target_date: goal.target_date || "", monthly_contribution: goal.monthly_contribution || "",
  } : { ...blankGoal });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [invalid, setInvalid] = useState("");
  const focus = useRef(null);
  const submitLock = useRef(false);
  const fundamentals = step === 0 || Boolean(goal);
  const timing = step === 1 || Boolean(goal);

  useEffect(() => { focus.current?.focus(); }, [step]);

  function change(event) {
    const { name, value } = event.target;
    setDraft((previous) => ({ ...previous, [name]: value }));
    setInvalid("");
    setError("");
  }

  async function submit(event) {
    event.preventDefault();
    if (submitLock.current) return;
    const { errors, payload } = goalDraft(timing ? draft : { ...draft, target_date: "", monthly_contribution: "" });
    const firstError = Object.keys(errors)[0];
    if (firstError) {
      setInvalid(firstError);
      setError(errors[firstError]);
      event.currentTarget.elements.namedItem(firstError)?.focus();
      return;
    }
    if (!goal && step === 0) {
      setStep(1);
      return;
    }
    submitLock.current = true;
    setBusy(true);
    setError("");
    try {
      await onSave(payload, goal);
    } catch (failure) {
      setError(goalError(failure, "Could not save this goal. Try again."));
    } finally {
      submitLock.current = false;
      setBusy(false);
    }
  }

  return <GoalDialog title={goal ? "Edit goal" : "Create a savings goal"} onClose={onClose} busy={busy}>
    {!goal && <p className="goals-muted" aria-live="polite">Step {step + 1} of 2 · {step === 0 ? "Goal details" : "Savings plan"}</p>}
    <form onSubmit={submit}>
      <fieldset className="goals-fields" disabled={busy}>
        {fundamentals && <>
          <label className="goals-full-field">Goal name
            <input ref={focus} name="name" value={draft.name} onChange={change} required maxLength={120}
              placeholder="e.g. Emergency fund" aria-invalid={invalid === "name"} />
          </label>
          <label>Target amount
            <input name="target_amount" value={draft.target_amount} onChange={change} required inputMode="decimal"
              maxLength={15} aria-invalid={invalid === "target_amount"} />
          </label>
          <label>Currency
            <input name="currency" value={draft.currency} onChange={change} required maxLength={3}
              readOnly={Boolean(goal)} aria-invalid={invalid === "currency"} />
          </label>
        </>}
        {timing && <>
          <label>Target date <small>Optional</small>
            <input ref={goal ? undefined : focus} name="target_date" type="date" value={draft.target_date} onChange={change}
              max="9999-12-31" aria-invalid={invalid === "target_date"} />
          </label>
          <label>Monthly contribution <small>Optional · {draft.currency.toUpperCase()}</small>
            <input name="monthly_contribution" value={draft.monthly_contribution} onChange={change} inputMode="decimal"
              maxLength={15} aria-invalid={invalid === "monthly_contribution"} />
          </label>
        </>}
      </fieldset>
      {timing && <p className="goals-muted">The monthly rate is used to estimate the completion date.</p>}
      {error && <p className="goals-error" role="alert">{error}</p>}
      <div className="goals-actions goals-dialog-actions">
        {!goal && step === 1 && <button type="button" onClick={() => { setStep(0); setError(""); setInvalid(""); }} disabled={busy}>Back</button>}
        <button type="submit" className="goals-primary" disabled={busy}>
          {busy ? "Saving…" : !goal && step === 0 ? "Continue" : goal ? "Save changes" : "Create goal"}
        </button>
      </div>
    </form>
  </GoalDialog>;
}

export function ContributionDialog({ goal, onClose, onRecorded }) {
  const [draft, setDraft] = useState({ kind: "contribution", amount: "", note: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const attempt = useRef(null);
  const amountInput = useRef(null);
  const locked = useRef(false);

  useEffect(() => { amountInput.current?.focus(); }, []);

  function change(event) {
    const { name, value } = event.target;
    setDraft((previous) => ({ ...previous, [name]: value }));
    setError("");
  }

  async function submit(event) {
    event.preventDefault();
    if (locked.current) return;
    const { payload, error: validation } = ledgerDraft(draft, goal);
    if (validation) {
      setError(validation);
      amountInput.current?.focus();
      return;
    }
    const fingerprint = JSON.stringify(payload);
    if (attempt.current?.fingerprint !== fingerprint) {
      attempt.current = { fingerprint, id: requestId() };
    }
    locked.current = true;
    setBusy(true);
    setError("");
    try {
      const { data } = await api.post(`${goalEndpoint(goal.id)}contributions/`, { ...payload, request_id: attempt.current.id },
        { timeout: 12_000 });
      onRecorded(data.goal, goal, payload.kind);
    } catch (failure) {
      setError(goalError(failure, "Could not confirm the entry. Retry with the same details to avoid a duplicate."));
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }

  return <GoalDialog title="Record goal activity" onClose={onClose} busy={busy}>
    <p className="goals-muted">{goal.name} · {money(goal.current_amount, goal.currency)} recorded</p>
    <form onSubmit={submit}>
      <fieldset className="goals-fields" disabled={busy}>
        <label>Activity
          <select name="kind" value={draft.kind} onChange={change}>
            <option value="contribution">Contribution</option><option value="withdrawal">Withdrawal</option>
          </select>
        </label>
        <label>Amount ({goal.currency})
          <input ref={amountInput} name="amount" value={draft.amount} onChange={change} inputMode="decimal" required maxLength={15} />
        </label>
        <label className="goals-full-field">Note <small>Optional</small>
          <textarea name="note" value={draft.note} onChange={change} rows={2} maxLength={255} />
        </label>
      </fieldset>
      {error && <p className="goals-error" role="alert">{error}</p>}
      <div className="goals-actions goals-dialog-actions">
        <button className="goals-primary" type="submit" disabled={busy}>
          {busy ? "Recording…" : draft.kind === "contribution" ? "Record contribution" : "Record withdrawal"}
        </button>
      </div>
    </form>
  </GoalDialog>;
}

GoalDialog.propTypes = {
  title: PropTypes.string.isRequired, children: PropTypes.node.isRequired, onClose: PropTypes.func.isRequired, busy: PropTypes.bool,
};
GoalEditor.propTypes = { goal: goalShape, onClose: PropTypes.func.isRequired, onSave: PropTypes.func.isRequired };
ContributionDialog.propTypes = { goal: goalShape.isRequired, onClose: PropTypes.func.isRequired, onRecorded: PropTypes.func.isRequired };

export function ArchiveGoalDialog({ goal, onClose, onSave }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const locked = useRef(false);
  const action = goal.archived ? "Restore" : "Archive";

  async function submit(event) {
    event.preventDefault();
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    setError("");
    try {
      await onSave({ archived: !goal.archived }, goal);
    } catch (failure) {
      setError(goalError(failure, "Could not update this goal. Try again."));
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }

  return <GoalDialog title={`${action} goal`} busy={busy} onClose={onClose}>
    <p>{goal.archived ? `Restore “${goal.name}” to record new activity.` :
      `Archive “${goal.name}” and keep its contribution history available.`}</p>
    <form onSubmit={submit}>
      {error && <p className="goals-error" role="alert">{error}</p>}
      <div className="goals-actions goals-dialog-actions">
        <button type="button" onClick={onClose} disabled={busy}>Cancel</button>
        <button className="goals-primary" type="submit" disabled={busy}>{busy ? "Saving…" : `${action} goal`}</button>
      </div>
    </form>
  </GoalDialog>;
}

ArchiveGoalDialog.propTypes = { goal: goalShape.isRequired, onClose: PropTypes.func.isRequired, onSave: PropTypes.func.isRequired };
