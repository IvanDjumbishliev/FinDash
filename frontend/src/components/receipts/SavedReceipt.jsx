import { useEffect, useRef, useState } from "react";
import PropTypes from "prop-types";
import { Link } from "react-router-dom";
import toast from "react-hot-toast";
import api from "../../api";
import { money } from "../../copilotPresentation";
import { confirmationBody, receiptApiError, receiptDate, reviewFields } from "../../receiptScanner";
import ReceiptReview, { ReceiptTotals } from "./ReceiptReview";

export default function SavedReceipt({ receipt, onChange, onDelete }) {
  const [fields, setFields] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [matches, setMatches] = useState(null);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const pending = useRef(null);
  const path = `/api/receipts/${receipt.id}/`;

  useEffect(() => () => pending.current?.abort(), []);

  async function run(operation, action) {
    if (pending.current) return;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(operation);
    setError("");
    try {
      await action({ signal: controller.signal, timeout: 15000 });
    } catch (failure) {
      if (!controller.signal.aborted) setError(receiptApiError(failure, "The request could not be completed. Try again."));
    } finally {
      if (!controller.signal.aborted) setBusy("");
      pending.current = null;
    }
  }

  function correct() {
    let body;
    try {
      const correction = confirmationBody(undefined, fields);
      body = { ...correction, items: correction.items.map((item, index) => ({
        ...item, id: fields.items[index].id, product: fields.items[index].product ?? null, brand: fields.items[index].brand ?? "",
      })) };
    } catch (failure) {
      setError(failure.message);
      return;
    }
    run("edit", async (options) => {
      const { data } = await api.patch(path, body, options);
      if (options.signal.aborted) return;
      onChange(data);
      setFields(null);
      setMatches(null);
      setSelected("");
      toast.success("Receipt updated");
    });
  }

  function loadMatches() {
    run("matches", async (options) => {
      const { data } = await api.get(`${path}reconciliation/`, options);
      if (!options.signal.aborted) {
        setMatches(data);
        setSelected("");
      }
    });
  }

  function reconcile(transaction) {
    run("link", async (options) => {
      const { data } = await api.patch(`${path}reconciliation/`, { transaction }, options);
      if (options.signal.aborted) return;
      onChange(data);
      setMatches(null);
      setSelected("");
      toast.success(transaction == null ? "Payment unlinked" : "Payment linked");
    });
  }

  return <section className="dash-panel receipt-panel" aria-labelledby="saved-receipt-heading">
    <h2 id="saved-receipt-heading">{receipt.merchant}</h2>
    <p className="receipt-muted">{receiptDate(receipt.purchased_at)} · {money(receipt.total, receipt.currency)}</p>
    {error && <p role="alert" className="receipt-callout">{error}</p>}
    {fields ? <ReceiptReview fields={fields} setFields={setFields}
      onContinue={correct} onCancel={() => { setFields(null); setError(""); }}
      duplicate={false} busy={busy === "edit"} submitLabel="Save corrections" cancelLabel="Cancel edits" /> : <>
      <h3>Saved items</h3>
      <ul className="receipt-breakdown receipt-saved-items">
        {receipt.items.map((item, index) => <li key={`${item.original_description}-${index}`}>
          <div><strong>{item.original_description}</strong><span>{money(item.line_total, receipt.currency)}</span></div>
          <small>{item.category || "Uncategorized"}{item.quantity != null && ` · ${item.quantity} ${item.unit || ""}`}
            {item.discount != null && ` · Discount ${money(item.discount, receipt.currency)}`}</small>
          {Number(item.line_total) >= 0 && (item.quantity == null || Number(item.quantity) > 0) &&
            <button type="button" className="dash-button" disabled={!!busy} onClick={() => run("pantry", async (options) => {
              const response = await api.post("/api/pantry/from-receipt/", { receipt_item: item.id }, options);
              if (!options.signal.aborted) toast.success(response.status === 201 ? "Added to pantry as an estimate." : "This receipt item is already in your pantry.");
            })}>Add to pantry</button>}
          <Link className="dash-link" to={`/warranties?receipt=${receipt.id}&item=${item.id}`}>Track warranty</Link>
        </li>)}
      </ul>
      <ReceiptTotals receipt={receipt} />
      <div className="receipt-actions">
        <button className="dash-button" type="button" disabled={!!busy} onClick={() => {
          setFields(reviewFields(receipt)); setError(""); setConfirmDelete(false);
        }}>Edit receipt</button>
        {!confirmDelete && <button className="dash-button" type="button" disabled={!!busy}
          onClick={() => setConfirmDelete(true)}>Delete receipt</button>}
      </div>
      {confirmDelete && <div className="receipt-callout receipt-delete">
        <p>Delete this receipt and its product spending records? The bank transaction will remain in FinDash.</p>
        <div className="receipt-actions">
          <button className="dash-button" type="button" disabled={!!busy} onClick={() => run("delete", async (options) => {
            await api.delete(path, options);
            if (options.signal.aborted) return;
            toast.success("Receipt deleted");
            onDelete();
          })}>{busy === "delete" ? "Deleting…" : "Confirm deletion"}</button>
          <button className="dash-button" type="button" disabled={!!busy} onClick={() => setConfirmDelete(false)}>Keep receipt</button>
        </div>
      </div>}

      <section className="receipt-payment" aria-label="Bank payment">
        <h3>Bank payment</h3>
        <p>{receipt.transaction
          ? receipt.reconciliation_valid ? "Linked to a matching transaction." : "The linked transaction no longer matches this receipt."
          : "No bank transaction linked."}</p>
        <div className="receipt-actions">
          <button className="dash-button" type="button" disabled={!!busy} onClick={loadMatches}>
            {busy === "matches" ? "Finding payments…" : "Find matching payments"}
          </button>
          {receipt.transaction && <button className="dash-button" type="button" disabled={!!busy} onClick={() => reconcile(null)}>Unlink payment</button>}
        </div>
        {matches && (matches.length ? <fieldset className="receipt-match-list" disabled={!!busy}>
          <legend>Choose the bank payment for this receipt</legend>
          {matches.map((match) => <label key={match.id}>
            <input type="radio" name="receipt-payment" value={match.id} checked={selected === String(match.id)}
              onChange={(event) => setSelected(event.target.value)} />
            <span><strong>{match.merchant || "Merchant unavailable"}</strong> · {receiptDate(match.timestamp)} · {money(match.amount, match.currency)}
              <small>{match.confidence === "high" ? "Same merchant and date" : "Review match"} · {match.days_apart} {match.days_apart === 1 ? "day" : "days"} apart</small>
            </span>
          </label>)}
          <button className="dash-button dash-primary" type="button" disabled={!selected || !!busy}
            onClick={() => reconcile(Number(selected))}>Link selected payment</button>
        </fieldset> : <p role="status" className="receipt-muted">No compatible payments were found within three days of the purchase.</p>)}
      </section>
    </>}
  </section>;
}

SavedReceipt.propTypes = { receipt: PropTypes.shape({
  id: PropTypes.string.isRequired, merchant: PropTypes.string.isRequired, purchased_at: PropTypes.string.isRequired,
  currency: PropTypes.string.isRequired, total: PropTypes.string.isRequired, transaction: PropTypes.number,
  reconciliation_valid: PropTypes.bool.isRequired, items: PropTypes.arrayOf(PropTypes.object).isRequired,
}).isRequired, onChange: PropTypes.func.isRequired, onDelete: PropTypes.func.isRequired };
