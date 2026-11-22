import PropTypes from "prop-types";
import { FiPlus, FiTrash2 } from "react-icons/fi";
import { money } from "../../copilotPresentation";
import { cents, MAX_RECEIPT_ITEMS, receiptTotals } from "../../receiptScanner";

const summaryType = {
  items: PropTypes.arrayOf(PropTypes.object).isRequired,
  currency: PropTypes.string,
  total: PropTypes.string,
  discounts: PropTypes.string,
};

export function ReceiptTotals({ receipt }) {
  const totals = receiptTotals(receipt.items, receipt.total);
  const amount = (value) => value == null ? "—" : money(value / 100, receipt.currency);
  return <section className="receipt-total-panel" aria-label="Receipt total check">
    <dl>
      <div><dt>Item total</dt><dd>{amount(totals.itemTotal)}</dd></div>
      <div><dt>Printed total</dt><dd>{amount(totals.receiptTotal)}</dd></div>
      <div><dt>Discounts shown</dt><dd>{amount(cents(receipt.discounts))}</dd></div>
      <div><dt>Difference</dt><dd>{amount(totals.difference)}</dd></div>
    </dl>
    <p className={totals.difference ? "receipt-warning-text" : "receipt-muted"}>
      {totals.difference == null ? "Enter valid line totals and the printed total to compare them."
        : totals.difference === 0 ? "The reviewed line totals match the printed total."
          : "The totals differ. Check the items, receipt-wide discounts, and tax before saving."}
    </p>
  </section>;
}

ReceiptTotals.propTypes = { receipt: PropTypes.shape(summaryType).isRequired };

const itemFields = [
  ["original_description", "Product name", 255, "text"],
  ["category", "Category", 120, "text"],
  ["quantity", "Quantity", 16, "decimal"],
  ["unit", "Unit"],
  ["unit_price", "Unit price", 16, "decimal"],
  ["discount", "Discount", 14, "decimal"],
  ["line_total", "Line total", 14, "decimal"],
];

const receiptFields = [
  ["merchant", "Merchant", "text", 255],
  ["date", "Purchase date", "date"],
  ["time", "Purchase time (Bulgaria)", "time"],
  ["currency", "Currency"],
  ["total", "Printed total", "text", 14],
  ["discounts", "Receipt discounts", "text", 14],
  ["tax_total", "Tax total", "text", 14],
  ["subtotal", "Subtotal", "text", 14],
  ["reference", "Receipt reference", "text", 128],
];

export default function ReceiptReview({ fields, setFields, onContinue, onCancel, onBack, duplicate, aiStatus, submitLabel = "Continue to confirmation", cancelLabel = "Cancel import", busy = false }) {
  function setField(key, value) {
    setFields((current) => ({ ...current, [key]: value }));
  }

  function changeItem(key, name, value) {
    setFields((current) => ({
      ...current,
      items: current.items.map((item) => {
        if (item.key !== key) return item;
        const updated = { ...item, [name]: value };
        if (name === "original_description") {
          updated.product = null;
          updated.brand = "";
        }
        return updated;
      }),
    }));
  }

  function addItem() {
    setFields((current) => ({
      ...current,
      items: [...current.items, { key: current.items.reduce((highest, item) => Math.max(highest, item.key), -1) + 1 }],
    }));
  }

  return <form onSubmit={(event) => { event.preventDefault(); onContinue(); }}>
    {duplicate && <p className="receipt-callout" role="status">
      Possible duplicate. A saved receipt has the same merchant, date, currency, and total. Check it before saving.
    </p>}
    {["unavailable", "not_configured"].includes(aiStatus) && <p className="receipt-callout" role="status">
      Gemini was unavailable. Review the results from local OCR below.
    </p>}
    {aiStatus === "used" && <p className="receipt-callout" role="status">
      Gemini helped match text from the receipt. Check suggested items and prices against the original photo.
    </p>}
    {fields.warnings?.length > 0 && <details className="receipt-callout">
      <summary>Scan warnings ({fields.warnings.length})</summary>
      <ul>{fields.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
    </details>}

    <fieldset className="receipt-editor-fields" disabled={busy}>
    <div className="receipt-form-grid">
      {receiptFields.map(([key, label, type, maxLength]) => <label key={key}>{label}
        {key === "currency" ? <select name={key} value={fields[key] ?? ""} required onChange={(event) => setField(key, event.target.value)}>
          <option value="">Choose currency</option><option value="EUR">EUR</option><option value="BGN">BGN</option>
        </select> : <input name={key} type={type} maxLength={maxLength} step={key === "time" ? 1 : undefined}
          inputMode={["total", "discounts", "tax_total", "subtotal"].includes(key) ? "decimal" : undefined}
          required={["merchant", "date", "time", "total"].includes(key)} value={fields[key] ?? ""}
          onChange={(event) => setField(key, event.target.value)} />}
      </label>)}
    </div>

    <div className="receipt-section-heading">
      <h3 id="receipt-items-heading">Receipt items ({fields.items.length})</h3>
      <button className="dash-button" type="button" onClick={addItem} disabled={fields.items.length >= MAX_RECEIPT_ITEMS}>
        <FiPlus aria-hidden="true" /> Add item
      </button>
    </div>
    {!fields.items.length ? <p className="receipt-muted">No items were recognized. Add the items from your receipt.</p>
      : <div className="receipt-table-wrap">
        <table className="receipt-table" aria-labelledby="receipt-items-heading" role="table">
          <thead role="rowgroup"><tr role="row">
            {itemFields.map(([key, label]) => <th key={key} scope="col" role="columnheader">{label}</th>)}
            <th scope="col" role="columnheader">Actions</th>
          </tr></thead>
          <tbody role="rowgroup">{fields.items.map((item, index) => <tr key={item.key} role="row" aria-label={`Item ${index + 1}`}>
            {itemFields.map(([key, label, maxLength, inputMode]) => <td key={key} role="cell">
              <label>
                <span className="receipt-mobile-label">{label}</span>
                {key === "unit"
                  ? <select aria-label={`${label} for item ${index + 1}`} value={item[key] ?? ""} onChange={(event) => changeItem(item.key, key, event.target.value)}>
                    <option value="">—</option><option value="item">Each</option><option value="kg">kg</option><option value="l">L</option>
                  </select>
                  : <input name={`receipt-item-${key}-${item.key}`} aria-label={`${label} for item ${index + 1}`}
                    inputMode={inputMode} maxLength={maxLength} value={item[key] ?? ""}
                    required={["original_description", "line_total"].includes(key)}
                    onChange={(event) => changeItem(item.key, key, event.target.value)} />}
              </label>
              {key === "original_description" && item.confidence != null && Number(item.confidence) < 0.8
                && <small className="receipt-item-review">Check extraction</small>}
            </td>)}
            <td role="cell"><button className="dash-button receipt-remove-item" type="button"
              aria-label={`Remove item ${index + 1}`} onClick={() => setFields((current) => ({
                ...current, items: current.items.filter((row) => row.key !== item.key),
              }))}><FiTrash2 aria-hidden="true" /><span className="receipt-mobile-label">Remove</span></button></td>
          </tr>)}</tbody>
        </table>
      </div>}
    <ReceiptTotals receipt={fields} />
    <div className="receipt-actions">
      <button className="dash-button dash-primary" type="submit">{busy ? "Saving…" : submitLabel}</button>
      {onBack && <button className="dash-button" type="button" onClick={onBack}>Back to photos</button>}
      <button className="dash-button" type="button" onClick={onCancel}>{cancelLabel}</button>
    </div>
    </fieldset>
  </form>;
}

ReceiptReview.propTypes = {
  fields: PropTypes.shape({ items: PropTypes.arrayOf(PropTypes.object).isRequired, warnings: PropTypes.arrayOf(PropTypes.string) }).isRequired,
  setFields: PropTypes.func.isRequired,
  onContinue: PropTypes.func.isRequired,
  onCancel: PropTypes.func.isRequired,
  onBack: PropTypes.func,
  duplicate: PropTypes.bool.isRequired,
  aiStatus: PropTypes.string,
  submitLabel: PropTypes.string,
  cancelLabel: PropTypes.string,
  busy: PropTypes.bool,
};
