import { useEffect, useRef, useState } from "react";
import PropTypes from "prop-types";
import api from "../api";
import StatementManagement from "./StatementManagement";
import StatementReview from "./StatementReview";
import { importSteps, importSummary, validateStatementFiles } from "../statementWizard";
import "../styles/components/StatementImport.css";

const endpoint = "/api/bank-statement/";
const fields = [
  ["date", "Date"], ["description", "Description"], ["amount", "Signed amount"],
  ["debit", "Debit"], ["credit", "Credit"], ["currency", "Currency"],
  ["direction", "Debit or credit indicator"], ["category", "FinDash category"],
  ["merchant", "Merchant"], ["reference", "Transaction reference"],
];

function StatementDialog({ onClose, onImported }) {
  const modal = useRef(null);
  const heading = useRef(null);
  const confirming = useRef(false);
  const [step, setStep] = useState("Upload");
  const [file, setFile] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [currency, setCurrency] = useState("");
  const [dateOrder, setDateOrder] = useState("DMY");
  const [consent, setConsent] = useState(false);
  const [aiConsent, setAiConsent] = useState(false);
  const [columns, setColumns] = useState([]);
  const [mapping, setMapping] = useState(null);
  const [showMapping, setShowMapping] = useState(false);
  const [preview, setPreview] = useState(null);
  const [receipt, setReceipt] = useState(null);
  const [busy, setBusy] = useState("");
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const dialog = modal.current;
    dialog.showModal();
    return () => dialog.close();
  }, []);

  useEffect(() => {
    modal.current.scrollTop = 0;
    heading.current.focus({ preventScroll: true });
  }, [step]);

  function discardPreview() {
    if (preview?.id && ["ready", "needs_mapping"].includes(preview.status)) {
      api.delete(`${endpoint}imports/${preview.id}/`).catch(() => {
        // The server expires the preview if it cannot be discarded now.
      });
    }
    setPreview(null);
    setError("");
  }

  function close() {
    discardPreview();
    onClose();
  }

  function chooseFiles(files) {
    discardPreview();
    setColumns([]);
    setMapping(null);
    setShowMapping(false);
    setConsent(false);
    setAiConsent(false);
    setDragging(false);
    const validation = validateStatementFiles(files);
    setFile(validation ? null : files[0]);
    setError(validation);
  }

  function receive(data) {
    setPreview(data);
    if (Array.isArray(data.columns)) {
      setColumns(data.columns);
      setMapping(data.mapping);
    }
    if (data.status === "needs_mapping") setShowMapping(true);
    setError(data.error || "");
    if (data.status === "ready") setStep("Review");
  }

  async function parse(event) {
    event.preventDefault();
    if (!file || busy) return;
    discardPreview();
    setStep("Parse");
    setProgress(null);
    setBusy("preview");
    const body = new FormData();
    body.append("file", file);
    body.append("date_order", dateOrder);
    if (currency.trim()) body.append("default_currency", currency.trim());
    if (mapping !== null) body.append("mapping", JSON.stringify(mapping));
    if (consent && /\.pdf$/i.test(file.name)) body.append("allow_external_processing", "true");
    if (aiConsent) body.append("allow_ai_categorization", "true");
    setConsent(false);
    setAiConsent(false);
    try {
      const { data } = await api.post(`${endpoint}preview/`, body, {
        timeout: 45000,
        onUploadProgress: ({ progress: ratio }) => {
          if (Number.isFinite(ratio)) setProgress(Math.min(100, Math.floor(ratio * 100)));
        },
      });
      if (!data?.id) throw new Error("Invalid preview");
      receive(data);
    } catch (failure) {
      if (failure.response?.data?.id) receive(failure.response.data);
      else setError("Could not preview the statement. You can retry the upload.");
    } finally {
      setBusy("");
    }
  }

  async function review(changes) {
    setBusy("review");
    setError("");
    try {
      const { data } = await api.patch(`${endpoint}imports/${preview.id}/`, { changes, revision: preview.revision }, { timeout: 15000 });
      setPreview({ ...preview, ...data });
      return true;
    } catch (failure) {
      const response = failure.response?.data;
      if (response?.id && response.status !== "ready") setStep("Parse");
      if (response?.id) setPreview({ ...preview, ...response });
      setError(response?.error || "Could not save the review. Your edits are still available to retry.");
      return false;
    } finally {
      setBusy("");
    }
  }

  function complete(data) {
    setReceipt(data);
    setPreview(data);
    setStep("Complete");
    onImported?.();
  }

  async function confirm() {
    if (confirming.current) return;
    confirming.current = true;
    setBusy("confirm");
    setError("");
    const url = `${endpoint}imports/${preview.id}/`;
    try {
      const { data } = await api.post(`${url}confirm/`, { revision: preview.revision }, { timeout: 15000 });
      if (data.status !== "imported") throw new Error("Import was not confirmed");
      complete(data);
    } catch (failure) {
      let response = failure.response?.data;
      if (!failure.response) {
        try {
          // A lost response can arrive after the server has committed the batch.
          const { data } = await api.get(url, { timeout: 6000 });
          if (data.status === "imported") {
            complete(data);
            return;
          }
          response = data;
        } catch {
          // A retry uses the same import ID, so it cannot create a second batch.
        }
      }
      if (response?.id) {
        setPreview({ ...preview, ...response });
        if (response.status !== "ready") setStep("Parse");
        else if (failure.response?.status === 409 || response.revision !== preview.revision) setStep("Review");
      }
      setError(response?.error || "Could not confirm the import. Retry this same preview.");
    } finally {
      confirming.current = false;
      setBusy("");
    }
  }

  function back(next) {
    setError("");
    setStep(next);
  }

  const rows = preview?.transactions ?? [];
  const summary = importSummary(rows);
  const activeStep = importSteps.indexOf(step);
  const rowErrors = preview?.errors?.filter(({ row }) => row) ?? [];
  const retryOptions = step === "Parse" && !busy;
  const canEditUpload = step === "Upload" || retryOptions;

  return (
    <dialog className="statement-dialog statement-wizard" ref={modal} aria-labelledby="statement-import-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) close();
      }}>
      <h2 id="statement-import-title">Import a bank statement</h2>
      <ol className="statement-steps" aria-label="Import steps">
        {importSteps.map((label, index) => (
          <li key={label} aria-current={label === step ? "step" : undefined}
            data-completed={index < activeStep || undefined}><span>{index + 1}</span>{label}</li>
        ))}
      </ol>
      <h3 ref={heading} tabIndex={-1} id="statement-step-title">{step}</h3>
      {error && <p className="statement-error" role="alert">{error}</p>}

      {canEditUpload && (
        <form onSubmit={parse} aria-labelledby="statement-step-title">
          {step === "Upload" && (
            <div className="statement-drop" data-dragging={dragging}
              onDragOver={(event) => {
                event.preventDefault();
                if (!dragging) setDragging(true);
              }}
              onDragLeave={(event) => {
                if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) setDragging(false);
              }}
              onDrop={(event) => {
                event.preventDefault();
                chooseFiles(Array.from(event.dataTransfer.files));
              }}>
              <label htmlFor="statement-upload">Drop a PDF or CSV here, or choose a file</label>
              <input id="statement-upload" type="file" accept=".pdf,.csv,application/pdf,text/csv"
                aria-describedby="statement-file-help" onChange={(event) => {
                  // Reset the native picker so choosing the same file also triggers a change.
                  chooseFiles(Array.from(event.target.files));
                  event.target.value = "";
                }} />
              <small id="statement-file-help">One file, up to 10 MB.</small>
              {file && <output aria-live="polite">Selected file: {file.name}</output>}
            </div>
          )}
          {retryOptions && file && <p className="statement-muted">Selected file: {file.name}</p>}
          <fieldset>
            <div className="statement-fields">
              <label>Default currency
                <input name="default_currency" value={currency} placeholder="e.g. EUR" maxLength={3}
                  onChange={(event) => setCurrency(event.target.value)} />
              </label>
              <label>Date order
                <select name="date_order" value={dateOrder} onChange={(event) => setDateOrder(event.target.value)}>
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
            {file && (
              <label className="statement-consent">
                <input type="checkbox" checked={aiConsent} onChange={(event) => setAiConsent(event.target.checked)} />
                For this preview, allow FinDash to send cleaned merchant names to Google Gemini to suggest categories for uncertain rows.
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
          {rowErrors.length > 0 && (
            <ul className="statement-errors">
              {rowErrors.map(({ row, message }, index) => <li key={index}>Row {row}. {message}</li>)}
            </ul>
          )}
          <div className="statement-actions">
            {retryOptions && <button type="button" onClick={() => back("Upload")}>Back to upload</button>}
            <button className="statement-primary" type="submit" disabled={!file}>
              {retryOptions ? "Retry parsing" : "Preview statement"}
            </button>
          </div>
        </form>
      )}

      {step === "Parse" && busy === "preview" && (
        <section aria-labelledby="statement-step-title" aria-busy="true">
          <p role="status">{progress === 100 ? "Upload complete. Parsing and validating transactions…" : "Uploading statement…"}</p>
          <progress aria-label={progress === 100 ? "Parsing statement" : "Uploading statement"}
            max={100} value={progress !== null && progress < 100 ? progress : undefined} />
          <p className="statement-muted">Transactions will be available for review before they are saved.</p>
        </section>
      )}

      {step === "Review" && preview?.status === "ready" && (
        <>
          {busy === "review" && <p role="status">Saving review…</p>}
          {preview.ai_status === "unavailable" && <p role="status">Gemini suggestions were unavailable. You can categorize rows manually.</p>}
          <StatementReview rows={rows} busy={Boolean(busy)} onReview={review}
            onNext={() => back("Confirm")} onBack={() => back("Upload")} />
        </>
      )}

      {step === "Confirm" && (
        <section aria-labelledby="statement-step-title">
          <p>Check the expected results before saving these transactions to FinDash.</p>
          <dl className="statement-totals">
            <div><dt>Total transactions</dt><dd>{summary.total}</dd></div>
            <div><dt>Selected for import</dt><dd>{summary.selected}</dd></div>
            <div><dt>Possible duplicates</dt><dd>{summary.duplicates}</dd></div>
            <div><dt>Expected to skip</dt><dd>{summary.skipped}</dd></div>
          </dl>
          <p className="statement-muted">Excluded and unapproved rows will be skipped. Any duplicate you explicitly approved will be imported.</p>
          {busy === "confirm" && <p role="status">Saving the approved transactions…</p>}
          <div className="statement-actions">
            <button type="button" disabled={Boolean(busy)} onClick={() => back("Review")}>Back to review</button>
            <button type="button" className="statement-primary" disabled={Boolean(busy) || !summary.selected} onClick={confirm}>
              {busy === "confirm" ? "Importing…" : error ? "Retry confirmation" : "Confirm import"}
            </button>
          </div>
        </section>
      )}

      {step === "Complete" && receipt && (
        <section aria-labelledby="statement-step-title">
          <p role="status">Your statement import is complete. Saved transactions are included in your spending analytics.</p>
          <dl className="statement-totals">
            <div><dt>Imported</dt><dd>{receipt.imported_count}</dd></div>
            <div><dt>Skipped</dt><dd>{receipt.row_count - receipt.imported_count}</dd></div>
            <div><dt>Errors</dt><dd>{receipt.errors.length}</dd></div>
          </dl>
          {receipt.errors.length > 0 && <ul className="statement-errors">
            {receipt.errors.map(({ row, message }, index) => <li key={index}>{row && `Row ${row}. `}{message}</li>)}
          </ul>}
        </section>
      )}
      <button type="button" disabled={Boolean(busy)} onClick={close}>{step === "Complete" ? "Done" : "Close"}</button>
    </dialog>
  );
}

StatementDialog.propTypes = { onClose: PropTypes.func.isRequired, onImported: PropTypes.func };

export default function PDFenter({ onImported }) {
  const [open, setOpen] = useState(null);
  const trigger = useRef(null);
  function launch(event, view) {
    trigger.current = event.currentTarget;
    setOpen(view);
  }

  function close() {
    setOpen(null);
    requestAnimationFrame(() => trigger.current?.focus());
  }

  return (
    <div className="input_box statement-actions">
      <button className="submit_btn" type="button" onClick={(event) => launch(event, "upload")}>Upload statement</button>
      <button className="statement-secondary" type="button" onClick={(event) => launch(event, "history")}>Import history</button>
      <button className="statement-secondary" type="button" onClick={(event) => launch(event, "rules")}>Categorization rules</button>
      {open === "upload" && <StatementDialog onImported={onImported} onClose={close} />}
      {["history", "rules"].includes(open) && <StatementManagement initialView={open} onClose={close} />}
    </div>
  );
}

PDFenter.propTypes = { onImported: PropTypes.func };
