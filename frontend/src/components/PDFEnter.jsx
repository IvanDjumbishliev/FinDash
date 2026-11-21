import { useEffect, useRef, useState } from "react";
import PropTypes from "prop-types";
import toast from "react-hot-toast";
import api from "../api";
import "../styles/components/StatementImport.css";

const endpoint = "/api/bank-statement/";
const fields = [
  ["date", "Date"], ["description", "Description"], ["amount", "Signed amount"],
  ["debit", "Debit"], ["credit", "Credit"], ["currency", "Currency"],
  ["direction", "Debit or credit indicator"], ["category", "FinDash category"],
];
const pageSize = 25;

function StatementDialog({ onClose, onImported }) {
  const modal = useRef(null);
  const [file, setFile] = useState(null);
  const [currency, setCurrency] = useState("");
  const [dateOrder, setDateOrder] = useState("DMY");
  const [consent, setConsent] = useState(false);
  const [columns, setColumns] = useState([]);
  const [mapping, setMapping] = useState(null);
  const [showMapping, setShowMapping] = useState(false);
  const [preview, setPreview] = useState(null);
  const [page, setPage] = useState(0);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const dialog = modal.current;
    dialog.showModal();
    return () => dialog.close();
  }, []);

  function discardPreview() {
    if (preview?.id && ["ready", "needs_mapping"].includes(preview.status)) {
      api.delete(`${endpoint}imports/${preview.id}/`).catch(() => {
        // The server expires the preview if it cannot be discarded now.
      });
    }
    setPreview(null);
    setPage(0);
    setError("");
  }

  function close() {
    discardPreview();
    onClose();
  }

  function selectFile(event) {
    discardPreview();
    setColumns([]);
    setMapping(null);
    setShowMapping(false);
    setConsent(false);
    const selected = event.target.files[0];
    if (!selected) {
      setFile(null);
      return;
    }
    if (!/\.(csv|pdf)$/i.test(selected.name) || selected.size > 10 * 1024 * 1024 || selected.size === 0) {
      setFile(null);
      setError("Choose a non-empty CSV or PDF file no larger than 10 MB.");
      return;
    }
    setFile(selected);
  }

  function receive(data) {
    setPreview(data);
    setPage(0);
    if (Array.isArray(data.columns)) {
      setColumns(data.columns);
      setMapping(data.mapping);
    }
    if (data.status === "needs_mapping") setShowMapping(true);
    setError(data.error || "");
  }

  async function parse(event) {
    event.preventDefault();
    if (!file) return;
    discardPreview();
    setBusy("preview");
    const body = new FormData();
    body.append("file", file);
    body.append("date_order", dateOrder);
    if (currency.trim()) body.append("default_currency", currency.trim());
    if (mapping !== null) body.append("mapping", JSON.stringify(mapping));
    if (consent && /\.pdf$/i.test(file.name)) body.append("allow_external_processing", "true");
    setConsent(false);
    try {
      const { data } = await api.post(`${endpoint}preview/`, body, { timeout: 45000 });
      if (!data?.id) throw new Error("Invalid preview");
      receive(data);
    } catch (failure) {
      if (failure.response?.data?.id) receive(failure.response.data);
      else setError("Could not preview the statement. Try again.");
    } finally {
      setBusy("");
    }
  }

  async function confirm() {
    setBusy("confirm");
    setError("");
    try {
      const { data } = await api.post(`${endpoint}imports/${preview.id}/confirm/`, {}, { timeout: 15000 });
      if (data.status !== "imported") throw new Error("Import was not confirmed");
      toast.success(`Imported ${data.row_count} ${data.row_count === 1 ? "transaction" : "transactions"}.`);
      onImported?.();
      onClose();
    } catch (failure) {
      setError(failure.response?.data?.error || "Could not save the import. You can retry this preview.");
    } finally {
      setBusy("");
    }
  }

  const ready = preview?.status === "ready";
  const pages = ready ? Math.ceil(preview.row_count / pageSize) : 0;
  return (
    <dialog className="statement-dialog" ref={modal} aria-labelledby="statement-import-title" onCancel={(event) => {
      event.preventDefault();
      if (!busy) close();
    }}>
      <h2 id="statement-import-title">Import a bank statement</h2>
      <p>Upload a PDF or CSV, review the transactions, then confirm to save them.</p>
      <form onSubmit={parse}>
        <fieldset disabled={Boolean(busy)}>
          <div className="statement-fields">
            <label>Statement file
              <input type="file" accept=".pdf,.csv,application/pdf,text/csv" onChange={selectFile} />
            </label>
            <label>Default currency
              <input name="default_currency" value={currency} placeholder="e.g. EUR" maxLength={3} onChange={(event) => {
                discardPreview();
                setCurrency(event.target.value);
              }} />
            </label>
            <label>Date order
              <select name="date_order" value={dateOrder} onChange={(event) => {
                discardPreview();
                setDateOrder(event.target.value);
              }}>
                <option value="DMY">Day / month / year</option>
                <option value="MDY">Month / day / year</option>
              </select>
            </label>
          </div>
          {file && /\.pdf$/i.test(file.name) && (
            <label className="statement-consent">
              <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
              If local parsing fails, allow this PDF to be sent to Google Gemini for this preview.
            </label>
          )}
          {columns.length > 0 && (
            <div>
              <button type="button" aria-expanded={showMapping} aria-controls="statement-column-mapping"
                onClick={() => setShowMapping((value) => !value)}>CSV column mapping</button>
              <div id="statement-column-mapping" className="statement-fields" hidden={!showMapping}>
                {fields.map(([field, label]) => (
                  <label key={field}>{label}
                    <select name={`mapping-${field}`} value={mapping?.[field] || ""} onChange={(event) => {
                      const value = event.target.value;
                      discardPreview();
                      setMapping((previous) => {
                        const next = { ...previous };
                        if (value) next[field] = value;
                        else delete next[field];
                        return next;
                      });
                    }}>
                      <option value="">Unmapped</option>
                      {columns.map((column) => <option key={column}>{column}</option>)}
                    </select>
                  </label>
                ))}
              </div>
            </div>
          )}
        </fieldset>
        <button type="submit" disabled={!file || Boolean(busy) || ready}>Preview statement</button>
      </form>
      {busy && <p role="status">{busy === "preview" ? "Parsing statement…" : "Saving transactions…"}</p>}
      {error && <p className="statement-error" role="alert">{error}</p>}
      {preview?.errors?.some(({ row }) => row) && (
        <ul className="statement-errors">
          {preview.errors.map(({ row, message }, index) => <li key={index}>{row && `Row ${row}. `}{message}</li>)}
        </ul>
      )}
      {ready && (
        <section aria-label="Statement preview">
          <h3>Preview · {preview.row_count} {preview.row_count === 1 ? "transaction" : "transactions"}</h3>
          <p>Review the dates, amounts, and currencies before saving.</p>
          <div className="statement-table" tabIndex={0} role="region" aria-label="Parsed transactions">
            <table>
              <thead><tr><th>Date</th><th>Description</th><th>Category</th><th>Amount</th><th>Currency</th></tr></thead>
              <tbody>{preview.transactions.slice(page * pageSize, (page + 1) * pageSize).map((row, index) => (
                <tr key={index}>
                  <td>{row.timestamp.slice(0, 10)}</td><td>{row.particulars}</td>
                  <td>{row.category}</td><td>{row.amount}</td><td>{row.currency}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          {pages > 1 && <div className="statement-actions">
            <button type="button" disabled={page === 0} onClick={() => setPage((value) => value - 1)}>Previous</button>
            <span>Page {page + 1} of {pages}</span>
            <button type="button" disabled={page + 1 === pages} onClick={() => setPage((value) => value + 1)}>Next</button>
          </div>}
        </section>
      )}
      <div className="statement-actions">
        {ready && <button type="button" className="statement-primary" disabled={Boolean(busy)} onClick={confirm}>Confirm import</button>}
        <button type="button" disabled={Boolean(busy)} onClick={close}>Close</button>
      </div>
    </dialog>
  );
}

StatementDialog.propTypes = { onClose: PropTypes.func.isRequired, onImported: PropTypes.func };

export default function PDFenter({ onImported }) {
  const [open, setOpen] = useState(false);
  const trigger = useRef(null);
  return (
    <div className="input_box">
      <button ref={trigger} className="submit_btn" type="button" onClick={() => setOpen(true)}>Upload statement</button>
      {open && <StatementDialog onImported={onImported} onClose={() => {
        setOpen(false);
        requestAnimationFrame(() => trigger.current?.focus());
      }} />}
    </div>
  );
}

PDFenter.propTypes = { onImported: PropTypes.func };
