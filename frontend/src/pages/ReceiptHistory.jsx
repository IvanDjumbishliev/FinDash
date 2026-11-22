import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import api from "../api";
import { money } from "../copilotPresentation";
import { receiptApiError, receiptDate } from "../receiptScanner";
import { DashboardError, DashboardLoading } from "../components/DashboardFeedback";
import ReceiptStatistics from "../components/receipts/ReceiptStatistics";
import SavedReceipt from "../components/receipts/SavedReceipt";
import "../styles/pages/Receipts.css";

const endpoint = "/api/receipts/";
const empty = { store: "", product: "", start: "", end: "" };
const filters = [["store", "Store"], ["product", "Product"], ["start", "From date"], ["end", "Through date"]];

function useReceiptData(path, params, version) {
  const [result, setResult] = useState(null);
  const query = new URLSearchParams(params).toString();
  const key = `${path}:${query}:${version}`;
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    api.get(path, { params: new URLSearchParams(query), signal: controller.signal, timeout: 15000 })
      .then(({ data }) => {
        if (!controller.signal.aborted) setResult({ key, data });
      }).catch((failure) => {
        if (!controller.signal.aborted) setResult({ key, error: receiptApiError(failure, "Could not load receipt data.") });
      });
    return () => controller.abort();
  }, [path, query, key]);
  return result?.key === key ? result : null;
}

export default function ReceiptHistory() {
  const [navigation, setNavigation] = useSearchParams();
  const receiptId = navigation.get("receipt");
  const selected = /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(receiptId || "") ? receiptId : null;
  const [draft, setDraft] = useState(empty);
  const [activeFilters, setActiveFilters] = useState({});
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [detailRevision, setDetailRevision] = useState(0);
  const [override, setOverride] = useState(null);
  const [filterError, setFilterError] = useState("");
  const list = useReceiptData(endpoint, { ...activeFilters, page }, revision);
  const statistics = useReceiptData(`${endpoint}statistics/`, activeFilters, revision);
  const detail = useReceiptData(selected ? `${endpoint}${selected}/` : null, {}, detailRevision);
  const current = override?.id === selected ? override : detail?.data;
  const retry = () => setRevision((value) => value + 1);

  function apply(event) {
    event.preventDefault();
    if (draft.start && draft.end && draft.start > draft.end) {
      setFilterError("The through date must be on or after the from date.");
      return;
    }
    setFilterError("");
    setActiveFilters(Object.fromEntries(Object.entries(draft).map(([key, value]) => [key, value.trim()]).filter(([, value]) => value)));
    setPage(1);
  }

  return <main className="dashboard-shell receipt-scanner receipt-history">
    <header className="market-heading">
      <h1>Receipt history</h1>
      <p>Find saved receipts, review product spending, and link purchases to bank payments.</p>
      <Link to="/receipts" className="dash-link">Scan a receipt</Link>
    </header>

    <section className="dash-panel receipt-panel" aria-labelledby="receipt-search-heading">
      <h2 id="receipt-search-heading">Find receipts</h2>
      <form onSubmit={apply}>
        <div className="receipt-form-grid">
          {filters.map(([key, label]) => <label key={key}>{label}
            <input name={key} type={key === "start" || key === "end" ? "date" : "search"}
              maxLength={120} value={draft[key]} onChange={(event) => setDraft({ ...draft, [key]: event.target.value })} />
          </label>)}
        </div>
        {filterError && <p role="alert" className="receipt-callout">{filterError}</p>}
        <div className="receipt-actions receipt-filter-actions">
          <button type="submit" className="dash-button dash-primary">Search receipts</button>
          <button type="button" className="dash-button" onClick={() => {
            setDraft(empty); setActiveFilters({}); setPage(1); setFilterError("");
          }}>Clear filters</button>
        </div>
      </form>
    </section>

    <div className="receipt-history-grid">
      <section className="dash-panel receipt-panel" aria-labelledby="receipt-list-heading">
        <h2 id="receipt-list-heading">Saved receipts</h2>
        {!list ? <DashboardLoading label="Loading saved receipts" /> : list.error
          ? <DashboardError onRetry={retry}>{list.error}</DashboardError>
          : list.data.results.length ? <>
            <p className="receipt-muted">{list.data.count} {list.data.count === 1 ? "receipt" : "receipts"}</p>
            <ul className="receipt-history-list">
              {list.data.results.map((receipt) => <li key={receipt.id}>
                <Link to={`?receipt=${receipt.id}`} aria-current={receipt.id === selected ? "true" : undefined}>
                  <strong>{receipt.merchant}</strong>
                  <span>{receiptDate(receipt.purchased_at)} · {money(receipt.total, receipt.currency)}</span>
                  <small>{receipt.reconciliation_valid ? "Payment linked" : receipt.transaction ? "Review payment link" : "Unlinked"}</small>
                </Link>
              </li>)}
            </ul>
            {list.data.previous || list.data.next ? <nav className="receipt-actions" aria-label="Receipt pages">
              <button type="button" className="dash-button" disabled={!list.data.previous} onClick={() => setPage(page - 1)}>Previous</button>
              <button type="button" className="dash-button" disabled={!list.data.next} onClick={() => setPage(page + 1)}>Next</button>
            </nav> : null}
          </> : <p className="receipt-muted">No receipts match. Clear the filters or scan a shopping receipt.</p>}
      </section>

      {selected && (current ? <SavedReceipt key={selected} receipt={current} onChange={(data) => {
        setOverride(data); retry();
      }} onDelete={() => {
        setNavigation({}); setOverride(null); setPage(1); retry();
      }} /> : <section className="dash-panel receipt-panel">
        {detail?.error ? <DashboardError onRetry={() => setDetailRevision((value) => value + 1)}>{detail.error}</DashboardError>
          : <DashboardLoading label="Loading selected receipt" />}
      </section>)}
    </div>

    <section className="dash-panel receipt-panel" aria-labelledby="receipt-statistics-heading">
      <h2 id="receipt-statistics-heading">Receipt spending</h2>
      {!statistics ? <DashboardLoading label="Loading receipt spending" />
        : statistics.error ? <DashboardError onRetry={retry}>{statistics.error}</DashboardError>
          : <ReceiptStatistics statistics={statistics.data} />}
    </section>
  </main>;
}
