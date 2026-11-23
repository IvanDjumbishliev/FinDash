import { useEffect, useRef, useState } from "react";
import PropTypes from "prop-types";
import { Link, useSearchParams } from "react-router-dom";
import { FiShield, FiFileText } from "react-icons/fi";
import toast from "react-hot-toast";
import api from "../api";
import { DashboardError, DashboardLoading } from "../components/DashboardFeedback";
import { displayDate } from "../copilotPresentation";
import { receiptApiError, receiptDate } from "../receiptScanner";
import "../styles/pages/Warranties.css";

const endpoint = "/api/warranties/";
const receiptPattern = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
const sourceLabels = { manual: "Entered by you", receipt: "From confirmed receipt", calculated: "Calculated from entered duration" };
const supportedImages = ".jpg,.jpeg,.png,.webp,.heic,.heif,image/jpeg,image/png,image/webp,image/heic,image/heif";

function WarrantyEditor({ warranty, receipt, item, onSave, onClose, busy }) {
  const [form, setForm] = useState(() => ({
    product_name: warranty?.product_name || "", retailer: warranty?.retailer || "", purchased_on: warranty?.purchased_on || "",
    mode: warranty?.duration_months != null ? "months" : warranty ? "date" : "months",
    duration_months: warranty?.duration_months ?? "", expires_on: warranty?.expires_on || "",
    reminder_days: warranty?.reminder_days.join(", ") || "",
  }));
  const [error, setError] = useState("");
  const heading = useRef(null);
  useEffect(() => heading.current?.focus(), []);
  const change = (key, value) => setForm((previous) => ({ ...previous, [key]: value }));

  function submit(event) {
    event.preventDefault();
    const values = form.reminder_days.trim() ? form.reminder_days.split(",").map((value) => value.trim()) : [];
    if (values.length > 4 || values.some((value) => !/^\d{1,3}$/.test(value) || Number(value) > 365)) {
      setError("Enter up to four reminder offsets between 0 and 365, separated by commas.");
      return;
    }
    setError("");
    const purchase = item ? { receipt_item: item.id } : {
      product_name: form.product_name.trim(), retailer: form.retailer.trim(), purchased_on: form.purchased_on,
    };
    onSave({
      ...purchase,
      duration_months: form.mode === "months" ? Number(form.duration_months) : null,
      ...(form.mode === "date" ? { expires_on: form.expires_on } : {}),
      reminder_days: values.map(Number),
    });
  }

  return <section className="dash-panel warranty-panel" aria-labelledby="warranty-editor-heading">
    <h2 id="warranty-editor-heading" ref={heading} tabIndex={-1}>{warranty ? "Edit warranty" : "Add warranty"}</h2>
    <form onSubmit={submit}>
      <fieldset disabled={busy}>
        {item ? <p><strong>{item.original_description}</strong> · {receipt.merchant} · {receiptDate(receipt.purchased_at)} <small>From confirmed receipt</small></p>
          : <div className="warranty-fields">
            <label>Product name<input required maxLength={255} value={form.product_name} onChange={(event) => change("product_name", event.target.value)} /></label>
            <label>Retailer<input required maxLength={255} value={form.retailer} onChange={(event) => change("retailer", event.target.value)} /></label>
            <label>Purchase date<input required type="date" value={form.purchased_on} onChange={(event) => change("purchased_on", event.target.value)} /></label>
          </div>}
        <div className="warranty-fields">
          <label>Warranty terms<select value={form.mode} onChange={(event) => change("mode", event.target.value)}>
            <option value="months">Documented duration</option><option value="date">Documented expiration date</option>
          </select></label>
          {form.mode === "months"
            ? <label>Duration (months)<input required type="number" min="1" max="600" step="1" value={form.duration_months}
              onChange={(event) => change("duration_months", event.target.value)} /></label>
            : <label>Expiration date<input required type="date" value={form.expires_on} onChange={(event) => change("expires_on", event.target.value)} /></label>}
          <label>Remind me (days before expiry)<input value={form.reminder_days} onChange={(event) => change("reminder_days", event.target.value)} placeholder="30, 7, 1" maxLength={24} />
            <small>Use commas. Enter 0 for expiry day, or leave blank for no reminders.</small>
          </label>
        </div>
        <p className="warranty-muted">Enter the warranty terms listed by the retailer or manufacturer.</p>
        {error && <p role="alert">{error}</p>}
        <div className="dash-actions">
          <button className="dash-button dash-primary" type="submit">{busy ? "Saving…" : "Save warranty"}</button>
          <button className="dash-button" type="button" onClick={onClose}>Cancel</button>
        </div>
      </fieldset>
    </form>
  </section>;
}

WarrantyEditor.propTypes = {
  warranty: PropTypes.shape({ product_name: PropTypes.string, retailer: PropTypes.string, purchased_on: PropTypes.string,
    duration_months: PropTypes.number, expires_on: PropTypes.string, reminder_days: PropTypes.arrayOf(PropTypes.number) }),
  receipt: PropTypes.shape({ merchant: PropTypes.string, purchased_at: PropTypes.string }),
  item: PropTypes.shape({ id: PropTypes.number, original_description: PropTypes.string }),
  onSave: PropTypes.func.isRequired, onClose: PropTypes.func.isRequired, busy: PropTypes.bool.isRequired,
};

export default function Warranties() {
  const [params, setParams] = useSearchParams();
  const linkedReceipt = params.get("receipt");
  const itemId = params.get("item");
  const linking = receiptPattern.test(linkedReceipt || "") && /^\d+$/.test(itemId || "");
  const [linked, setLinked] = useState(null);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [result, setResult] = useState(null);
  const [editor, setEditor] = useState(null);
  const [deleteId, setDeleteId] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef(null);
  const key = JSON.stringify([search, status, page, revision]);
  const warranties = result?.key === key ? result : null;
  const context = linked?.id === linkedReceipt ? linked : null;
  const item = context?.data?.items.find((row) => String(row.id) === itemId);

  useEffect(() => () => pending.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController();
    api.get(endpoint, { params: { q: search, status: status || undefined, page }, signal: controller.signal, timeout: 12000 })
      .then(({ data }) => { if (!controller.signal.aborted) setResult({ key, data }); })
      .catch((failure) => { if (!controller.signal.aborted) setResult({ key, error: receiptApiError(failure, "Could not load warranties.") }); });
    return () => controller.abort();
  }, [key, page, search, status]);

  useEffect(() => {
    if (!linking) return;
    const controller = new AbortController();
    api.get(`/api/receipts/${linkedReceipt}/`, { signal: controller.signal, timeout: 12000 })
      .then(({ data }) => { if (!controller.signal.aborted) setLinked({ id: linkedReceipt, data }); })
      .catch(() => { if (!controller.signal.aborted) setLinked({ id: linkedReceipt, error: true }); });
    return () => controller.abort();
  }, [linking, linkedReceipt]);

  const refresh = () => setRevision((value) => value + 1);
  function closeEditor() {
    if (linking) setParams({});
    setEditor(null);
    setError("");
  }

  async function act(operation, message, done) {
    if (pending.current) return;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);
    setError("");
    try {
      await operation({ signal: controller.signal, timeout: 20000 });
      if (controller.signal.aborted) return;
      done?.();
      if (message) {
        refresh();
        toast.success(message);
      }
    } catch (failure) {
      if (!controller.signal.aborted) setError(receiptApiError(failure, "Could not complete the request. Try again."));
    } finally {
      pending.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  function upload(warranty, file) {
    if (!file) return;
    if (file.size > 8 * 1024 * 1024 || !/\.(jpe?g|png|webp|heic|heif)$/i.test(file.name)) {
      setError("Choose a JPEG, PNG, WebP or HEIC image up to 8 MB.");
      return;
    }
    const body = new FormData();
    body.append("file", file);
    act((options) => api.post(`${endpoint}${warranty.id}/proof/`, body, options), "Purchase proof saved");
  }

  function download(warranty) {
    act(async (options) => {
      const { data } = await api.get(`${endpoint}${warranty.id}/proof/`, { ...options, responseType: "blob" });
      if (options.signal.aborted) return;
      const url = URL.createObjectURL(data);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "purchase-proof.png";
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
  }

  return <main className="dashboard-shell warranty-page">
    <header className="market-heading">
      <h1><FiShield aria-hidden="true" /> Warranty Vault</h1>
      <p>Track expiration dates and keep your proof of purchase in one private place.</p>
      <div className="dash-actions">
        <button type="button" className="dash-button dash-primary" disabled={busy} onClick={() => {
          setParams({}); setEditor("new"); setError("");
        }}>Add manual warranty</button>
        <Link className="dash-link" to="/receipts/history">Choose a receipt item</Link>
        <Link className="dash-link" to="/notifications/settings">Notification settings</Link>
      </div>
    </header>
    {error && <p className="warranty-callout" role="alert">{error}</p>}
    {linking && !context && <DashboardLoading label="Loading receipt item" />}
    {linking && context && !item && <p className="warranty-callout" role="alert">
      This receipt item is unavailable. <Link to="/receipts/history">Return to receipt history</Link>.
    </p>}
    {(editor || item) && <WarrantyEditor key={item ? `receipt-${item.id}` : editor === "new" ? "new" : editor.id}
      warranty={editor && editor !== "new" ? editor : undefined} item={item} receipt={context?.data} busy={busy} onClose={closeEditor}
      onSave={(body) => act((options) => editor && editor !== "new"
        ? api.patch(`${endpoint}${editor.id}/`, body, options) : api.post(endpoint, body, options),
      editor && editor !== "new" ? "Warranty updated" : "Warranty saved", () => { closeEditor(); setPage(1); })} />}

    <section className="dash-panel warranty-panel" aria-labelledby="warranty-records">
      <h2 id="warranty-records">Your warranties</h2>
      <form className="warranty-filters" onSubmit={(event) => { event.preventDefault(); setSearch(query.trim()); setPage(1); }}>
        <label>Product or retailer <input type="search" maxLength={120} value={query} onChange={(event) => setQuery(event.target.value)} /></label>
        <label>Status <select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); }}>
          <option value="">All warranties</option><option value="active">Active</option><option value="expired">Expired</option>
        </select></label>
        <button type="submit" className="dash-button">Search warranties</button>
      </form>
      {!warranties ? <DashboardLoading label="Loading warranties" /> : warranties.error
        ? <DashboardError onRetry={refresh}>{warranties.error}</DashboardError> : !warranties.data.results.length
          ? <p className="warranty-muted">No warranties match. Add a warranty manually or from a saved receipt.</p> : <>
            <div className="warranty-grid">{warranties.data.results.map((warranty) => <article key={warranty.id}>
              <header><div><h3>{warranty.product_name}</h3><small>{sourceLabels[warranty.field_sources.product_name]}</small></div><span className="warranty-status" data-status={warranty.status}>{warranty.status}</span></header>
              <dl>
                {[["retailer", "Retailer", warranty.retailer],
                  ["purchased_on", "Purchased", displayDate(warranty.purchased_on)],
                  ["duration_months", "Duration", warranty.duration_months != null ? `${warranty.duration_months} months` : null],
                  ["expires_on", "Expiration", displayDate(warranty.expires_on)]].map(([key, label, value]) => value && <div key={key}>
                    <dt>{label}</dt><dd>{value}<small>{sourceLabels[warranty.field_sources[key]]}</small></dd>
                  </div>)}
              </dl>
              <p className="warranty-muted">{warranty.reminder_days.length
                ? `Reminder days: ${warranty.reminder_days.join(", ")} before expiry` : "Reminders off"}</p>
              {warranty.receipt_id && <Link className="dash-link" to={`/receipts/history?receipt=${warranty.receipt_id}`}>View linked receipt</Link>}
              <div className="dash-actions warranty-proof-actions">
                <label className="warranty-upload"><FiFileText aria-hidden="true" />
                  <span>{warranty.has_proof ? "Replace proof" : "Attach proof image"}</span>
                  <input aria-label={`Upload proof for ${warranty.product_name}`} type="file" accept={supportedImages} disabled={busy}
                    onChange={(event) => { upload(warranty, event.target.files[0]); event.target.value = ""; }} />
                </label>
                {warranty.has_proof && <>
                  <button className="dash-button" type="button" disabled={busy} onClick={() => download(warranty)}>Download proof</button>
                  <button className="dash-button" type="button" disabled={busy} onClick={() => act(
                    (options) => api.delete(`${endpoint}${warranty.id}/proof/`, options), "Purchase proof removed",
                  )}>Remove proof</button>
                </>}
              </div>
              <div className="dash-actions">
                <button className="dash-button" type="button" disabled={busy} onClick={() => {
                  setParams({}); setEditor(warranty); setError("");
                }}>Edit warranty</button>
                {deleteId === warranty.id ? <>
                  <button className="dash-button" type="button" disabled={busy} onClick={() => act(
                    (options) => api.delete(`${endpoint}${warranty.id}/`, options), "Warranty deleted",
                    () => { setDeleteId(null); setPage(1); if (editor?.id === warranty.id) setEditor(null); },
                  )}>Confirm delete warranty and proof</button>
                  <button className="dash-button" type="button" disabled={busy} onClick={() => setDeleteId(null)}>Keep warranty</button>
                </> : <button className="dash-button" type="button" disabled={busy} onClick={() => setDeleteId(warranty.id)}>Delete warranty</button>}
              </div>
            </article>)}</div>
            {(warranties.data.previous || warranties.data.next) && <nav className="dash-actions warranty-pages" aria-label="Warranty pages">
              <button type="button" className="dash-button" disabled={!warranties.data.previous} onClick={() => setPage(page - 1)}>Previous</button>
              <button type="button" className="dash-button" disabled={!warranties.data.next} onClick={() => setPage(page + 1)}>Next</button>
            </nav>}
          </>}
    </section>
  </main>;
}
