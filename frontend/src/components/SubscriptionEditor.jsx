import { useEffect, useRef, useState } from "react";
import PropTypes from "prop-types";
import { billingCycles, categories, statuses, subscriptionEdit } from "../subscriptions";

export default function SubscriptionEditor({ record, onSave, onClose, busy, error }) {
  const serverRecord = record && !record.local;
  const [draft, setDraft] = useState(() => ({
    merchant: record?.merchant ?? "",
    estimated_amount: record?.estimated_amount ?? "",
    currency: record?.currency ?? "",
    billing_frequency: record?.billing_frequency ?? "monthly",
    next_expected_payment: record?.next_expected_payment ?? "",
    tracking_status: record?.tracking_status ?? "active",
    category: record?.category ?? "Uncategorized",
  }));
  const [validation, setValidation] = useState("");
  const merchantInput = useRef(null);
  useEffect(() => merchantInput.current?.focus(), []);

  function change(event) {
    const { name, value } = event.target;
    setDraft((previous) => ({ ...previous, [name]: value }));
    setValidation("");
  }

  function submit(event) {
    event.preventDefault();
    try {
      onSave(subscriptionEdit(draft, record, record ? record.id : crypto.randomUUID()));
    } catch (failure) {
      setValidation(failure.message);
    }
  }

  return (
    <form className="subscription-panel subscription-editor" onSubmit={submit} aria-labelledby="subscription-editor-title">
      <h2 id="subscription-editor-title">{record ? "Edit subscription" : "Add subscription"}</h2>
      {!serverRecord && <p>Manual subscriptions are saved in this browser.</p>}
      <fieldset disabled={busy} className="subscription-fields">
        <label>Merchant<input ref={merchantInput} name="merchant" value={draft.merchant} onChange={change} required maxLength={255} /></label>
        <label>Amount per payment<input name="estimated_amount" inputMode="decimal" value={draft.estimated_amount} onChange={change} required /></label>
        <label>Currency<input name="currency" value={draft.currency} onChange={change} placeholder="e.g. EUR" maxLength={3} required readOnly={Boolean(serverRecord)} /></label>
        <label>Billing cycle
          <select name="billing_frequency" value={draft.billing_frequency} onChange={change} disabled={Boolean(serverRecord)}>
            {Object.entries(billingCycles).map(([key, cycle]) => <option key={key} value={key}>{cycle.label}</option>)}
          </select>
        </label>
        <label>Next payment<input name="next_expected_payment" type="date" value={draft.next_expected_payment} onChange={change} required /></label>
        <label>Category
          <select name="category" value={draft.category} onChange={change}>
            {categories.map((category) => <option key={category}>{category}</option>)}
          </select>
        </label>
        {record?.status !== "candidate" && (
          <label>Tracking status
            <select name="tracking_status" value={draft.tracking_status} onChange={change}>
              {["active", "paused", "canceled"].map((status) => <option key={status} value={status}>{statuses[status]}</option>)}
            </select>
          </label>
        )}
      </fieldset>
      {(validation || error) && <p role="alert">{validation || error}</p>}
      <div className="subscription-actions">
        <button type="submit" className="subscription-primary" disabled={busy}>{busy ? "Saving…" : "Save subscription"}</button>
        <button type="button" onClick={onClose} disabled={busy}>Close</button>
      </div>
    </form>
  );
}

SubscriptionEditor.propTypes = {
  record: PropTypes.shape({
    local: PropTypes.bool, id: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
    merchant: PropTypes.string, estimated_amount: PropTypes.string, currency: PropTypes.string,
    billing_frequency: PropTypes.string, next_expected_payment: PropTypes.string,
    tracking_status: PropTypes.string, category: PropTypes.string, status: PropTypes.string,
  }),
  onSave: PropTypes.func.isRequired,
  onClose: PropTypes.func.isRequired,
  busy: PropTypes.bool.isRequired,
  error: PropTypes.string,
};
