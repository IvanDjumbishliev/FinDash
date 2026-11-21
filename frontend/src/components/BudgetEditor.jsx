import { useEffect, useRef, useState } from "react";
import PropTypes from "prop-types";
import { budgetCategories, categoryLabel, budgetPayload } from "../budgets";

export default function BudgetEditor({ budget, month, busy, error, onSave, onArchive, onDelete, onClose }) {
  const modal = useRef(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [validation, setValidation] = useState("");
  const [draft, setDraft] = useState(() => ({
    category: budget?.category ?? "",
    period: budget?.period.slice(0, 7) ?? month,
    currency: budget?.currency ?? "",
    amount: budget?.amount ?? "",
    thresholds: (budget?.alert_thresholds ?? [50, 80, 100]).join(", "),
  }));

  useEffect(() => {
    const dialog = modal.current;
    dialog.showModal();
    return () => dialog.close();
  }, []);

  function change(event) {
    setDraft({ ...draft, [event.target.name]: event.target.value });
    setValidation("");
  }

  function submit(event) {
    event.preventDefault();
    try {
      onSave(budgetPayload(draft));
    } catch (failure) {
      setValidation(failure.message);
    }
  }

  return (
    <dialog ref={modal} className="budget-dialog" aria-labelledby="budget-editor-title" onCancel={(event) => {
      event.preventDefault();
      if (!busy) onClose();
    }}>
      <form onSubmit={submit}>
        <h2 id="budget-editor-title">{budget ? "Edit budget" : "Create budget"}</h2>
        <fieldset disabled={busy}>
          <label>Category
            <select name="category" value={draft.category} onChange={change}>
              <option value="">Overall budget</option>
              {budgetCategories.map((category) => <option key={category} value={category}>{categoryLabel(category)}</option>)}
            </select>
          </label>
          <label>Budget month
            <input name="period" type="month" value={draft.period} onChange={change}
              required min="0001-01" max="9999-11" placeholder="YYYY-MM" />
          </label>
          <label>Budget amount
            <input name="amount" inputMode="decimal" value={draft.amount} onChange={change} required />
          </label>
          <label>Currency
            <input name="currency" value={draft.currency} onChange={change} placeholder="e.g. EUR" required maxLength={3} />
          </label>
          <label className="budget-wide">Alert thresholds (%)
            <input name="thresholds" value={draft.thresholds} onChange={change}
              aria-describedby="budget-threshold-help" />
            <small id="budget-threshold-help">Separate with commas. Leave blank to disable thresholds.</small>
          </label>
        </fieldset>
        {(validation || error) && <p className="budget-feedback budget-error" role="alert">{validation || error}</p>}
        {confirmDelete && (
          <div className="budget-feedback" role="group" aria-label="Confirm budget deletion">
            <p>Permanently delete this budget? Its transactions will still be available.</p>
            <div className="budget-actions">
              <button type="button" className="budget-delete" disabled={busy} onClick={onDelete}>Delete permanently</button>
              <button type="button" disabled={busy} onClick={() => setConfirmDelete(false)}>Keep budget</button>
            </div>
          </div>
        )}
        <div className="budget-actions">
          <button type="submit" className="budget-primary" disabled={busy || confirmDelete}>{busy ? "Saving…" : "Save budget"}</button>
          <button type="button" disabled={busy} onClick={onClose}>Close</button>
          {budget && <>
            <button type="button" disabled={busy || confirmDelete} onClick={onArchive}>
              {budget.archived ? "Restore budget" : "Archive budget"}
            </button>
            <button type="button" disabled={busy || confirmDelete} onClick={() => setConfirmDelete(true)}>Delete budget</button>
          </>}
        </div>
      </form>
    </dialog>
  );
}

BudgetEditor.propTypes = {
  budget: PropTypes.shape({
    category: PropTypes.string, period: PropTypes.string, currency: PropTypes.string,
    amount: PropTypes.string, alert_thresholds: PropTypes.arrayOf(PropTypes.number),
    archived: PropTypes.bool,
  }),
  month: PropTypes.string.isRequired,
  busy: PropTypes.bool.isRequired,
  error: PropTypes.string,
  onSave: PropTypes.func.isRequired,
  onArchive: PropTypes.func.isRequired,
  onDelete: PropTypes.func.isRequired,
  onClose: PropTypes.func.isRequired,
};
