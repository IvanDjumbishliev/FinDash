import { useEffect, useRef, useState } from "react";
import { FiCheckCircle, FiFileText } from "react-icons/fi";
import { Link } from "react-router-dom";
import toast from "react-hot-toast";
import api from "../api";
import ReceiptUpload, { ReceiptPhoto } from "../components/receipts/ReceiptUpload";
import ReceiptReview, { ReceiptTotals } from "../components/receipts/ReceiptReview";
import { displayDate, money } from "../copilotPresentation";
import { confirmationBody, receiptApiError, reviewFields, rotateReceiptFile, validateReceiptImages } from "../receiptScanner";
import "../styles/pages/Receipts.css";

const steps = [["upload", "Upload"], ["extract", "Extract"], ["review", "Review"], ["confirm", "Confirm"], ["saved", "Saved"]];

export default function Receipts() {
  const [step, setStep] = useState("upload");
  const [pages, setPages] = useState([]);
  const [preview, setPreview] = useState(null);
  const [fields, setFields] = useState(null);
  const [body, setBody] = useState(null);
  const [receipt, setReceipt] = useState(null);
  const [error, setError] = useState("");
  const [progress, setProgress] = useState(null);
  const [saving, setSaving] = useState(false);
  const request = useRef(null);
  const nextPhoto = useRef(0);
  const heading = useRef(null);
  const stepIndex = steps.findIndex(([id]) => id === step);

  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => { heading.current.focus(); }, [step]);

  function reset() {
    request.current?.abort();
    request.current = null;
    setStep("upload");
    setPages([]);
    setPreview(null);
    setFields(null);
    setBody(null);
    setReceipt(null);
    setError("");
  }

  function selectFiles(files, source, replace) {
    const previous = replace ? [] : pages;
    const issue = validateReceiptImages([...previous.map((page) => page.file), ...files]);
    setError(issue);
    if (issue) return;
    const selected = files.map((file) => ({ file, source, turns: 0, id: nextPhoto.current++ }));
    setPages([...previous, ...selected]);
    setPreview(null);
  }

  async function scan({ allowAi, dateOrder }) {
    if (request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setStep("extract");
    setError("");
    setProgress(0);
    try {
      const images = [];
      for (const page of pages) images.push(await rotateReceiptFile(page));
      if (controller.signal.aborted) return;
      const issue = validateReceiptImages(images);
      if (issue) {
        setError(issue);
        setStep("upload");
        return;
      }
      const upload = new FormData();
      for (const image of images) upload.append("file", image);
      upload.append("date_order", dateOrder);
      upload.append("allow_ai", String(allowAi));
      const sources = new Set(pages.map(({ source }) => source));
      upload.append("source", sources.size === 1 ? pages[0].source : "upload");
      const { data } = await api.post("/api/receipts/preview/", upload, {
        signal: controller.signal, timeout: 95_000,
        onUploadProgress: ({ progress: ratio }) => {
          if (Number.isFinite(ratio) && !controller.signal.aborted) setProgress(Math.min(100, Math.floor(ratio * 100)));
        },
      });
      if (controller.signal.aborted) return;
      if (data?.status === "duplicate" && data.duplicate_id) {
        const existing = await api.get(`/api/receipts/${data.duplicate_id}/`, {
          signal: controller.signal, timeout: 12_000,
        });
        if (!controller.signal.aborted) {
          setReceipt({ ...existing.data, duplicate: true });
          setPages([]);
          setStep("saved");
        }
        return;
      }
      if (typeof data?.token !== "string" || !Array.isArray(data.receipt?.items)) throw new Error("Invalid receipt preview");
      setPreview(data);
      setFields(reviewFields(data.receipt));
      setStep("review");
    } catch (failure) {
      if (!controller.signal.aborted) {
        const fallback = failure.response || failure.code
          ? "The receipt could not be scanned. Try again or choose a clearer photo."
          : failure.message === "Invalid receipt preview" ? "The server did not return a receipt preview. Try scanning again." : failure.message;
        setError(receiptApiError(failure, fallback));
        setStep("upload");
      }
    } finally {
      if (request.current === controller) request.current = null;
    }
  }

  function review() {
    try {
      setBody(confirmationBody(preview.token, fields));
      setError("");
      setStep("confirm");
    } catch (failure) {
      setError(failure.message);
    }
  }

  async function save() {
    if (request.current || !body) return;
    const controller = new AbortController();
    request.current = controller;
    setSaving(true);
    setError("");
    try {
      const { data, status } = await api.post("/api/receipts/confirm/", body, {
        signal: controller.signal, timeout: 20_000,
      });
      if (controller.signal.aborted) return;
      if (!data?.id || data.status !== "confirmed") throw new Error("Invalid confirmation");
      setReceipt({ ...data, duplicate: status === 200 });
      setPages([]);
      setFields(null);
      setPreview(null);
      setBody(null);
      setStep("saved");
      if (status === 201) toast.success("Receipt saved");
    } catch (failure) {
      if (!controller.signal.aborted) setError(receiptApiError(failure, "Could not save the receipt. Your review is still here. Try Save receipt again."));
    } finally {
      if (request.current === controller) request.current = null;
      if (!controller.signal.aborted) setSaving(false);
    }
  }

  return <main className="dashboard-shell receipt-scanner">
    <header className="market-heading">
      <h1>Smart Receipt Scanner</h1>
      <p>Scan a shopping receipt, check each item, and save the reviewed purchase.</p>
      <Link to="/receipts/history" className="dash-link">Receipt history and spending</Link>
    </header>
    <ol className="receipt-steps" aria-label="Receipt import progress">
      {steps.map(([id, title], index) => <li key={id} aria-current={step === id ? "step" : undefined}
        data-complete={index < stepIndex}>{index < stepIndex ? <FiCheckCircle aria-hidden="true" /> : null}{title}</li>)}
    </ol>
    <section className="dash-panel receipt-panel" aria-labelledby="receipt-step-title">
      <h2 id="receipt-step-title" ref={heading} tabIndex={-1}>
        {{ upload: "Add receipt photos", extract: "Reading your receipt", review: "Review receipt", confirm: "Confirm import",
          saved: receipt?.duplicate ? "Receipt already saved" : "Receipt saved" }[step]}
      </h2>
      {error && <p className="receipt-callout" role="alert">{error}</p>}
      {step === "upload" && <ReceiptUpload pages={pages} onFiles={selectFiles}
        onRotate={(id) => setPages((current) => current.map((page) => page.id === id ? { ...page, turns: (page.turns + 1) % 4 } : page))}
        onRemove={(id) => { setPages((current) => current.filter((page) => page.id !== id)); setError(""); }} onScan={scan} />}
      {step === "extract" && <div className="receipt-processing">
        <p role="status">{progress < 100 ? "Preparing and uploading your photos…" : "Extracting products and totals…"}</p>
        <progress aria-label={progress < 100 ? "Photo upload" : "Receipt extraction"}
          value={progress < 100 ? progress : undefined} max="100" />
        <button className="dash-button" type="button" onClick={reset}>Cancel import</button>
      </div>}
      {step === "review" && <>
        <details className="receipt-reference-photos">
          <summary>View receipt photos</summary>
          <ol className="receipt-photos">{pages.map((page, index) => <ReceiptPhoto key={page.id} page={page} index={index} />)}</ol>
        </details>
        <ReceiptReview fields={fields} setFields={setFields}
        duplicate={Boolean(preview.possible_duplicate_ids?.length)} aiStatus={preview.ai_status || "not_requested"}
        onContinue={review} onCancel={reset} onBack={() => { setError(""); setStep("upload"); }} />
      </>}
      {step === "confirm" && <>
        <p><strong>{body.merchant}</strong> · {displayDate(body.purchased_at.slice(0, 10))} · {body.items.length} {body.items.length === 1 ? "item" : "items"}</p>
        {preview.possible_duplicate_ids?.length > 0 && <p className="receipt-callout">Possible duplicate. Verify this is a separate purchase before saving.</p>}
        <ReceiptTotals receipt={body} />
        <p className="receipt-muted">Saving adds the reviewed receipt to FinDash. Your bank transactions stay as they are.</p>
        <div className="receipt-actions">
          <button className="dash-button dash-primary" type="button" disabled={saving} onClick={save}>{saving ? "Saving…" : "Save receipt"}</button>
          <button className="dash-button" type="button" disabled={saving} onClick={() => { setError(""); setStep("review"); }}>Back to review</button>
          <button className="dash-button" type="button" disabled={saving} onClick={reset}>Cancel import</button>
        </div>
      </>}
      {step === "saved" && <>
        <div className="receipt-saved" role="status">
          <FiFileText aria-hidden="true" />
          <div><strong>{receipt.merchant}</strong>
            <p>{receipt.items.length} {receipt.items.length === 1 ? "item" : "items"} · {money(receipt.total, receipt.currency)}</p></div>
        </div>
        <p className="receipt-muted">{receipt.duplicate ? "This purchase already exists in your receipts." : "Your reviewed receipt and items were saved."}</p>
        <div className="receipt-actions">
          <button className="dash-button dash-primary" type="button" onClick={reset}>Scan another receipt</button>
          <Link className="dash-link" to={`/receipts/history?receipt=${receipt.id}`}>View saved receipt</Link>
        </div>
      </>}
    </section>
  </main>;
}
