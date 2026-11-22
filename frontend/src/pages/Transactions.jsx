import { useState, useEffect, useRef } from "react";
import api from "../api";
import { DashboardError, DashboardLoading } from "../components/DashboardFeedback";
import TransactionList from "../components/TransactionList";
import TransactionForm from "../components/TransactionForm";
import "../styles/pages/Transactions.css";

const PAGE_SIZE = 25;

export default function Transactions() {
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [result, setResult] = useState(null);
  const [notice, setNotice] = useState("");
  const [deleting, setDeleting] = useState(false);
  const deletePending = useRef(false);
  const version = `${offset}:${revision}`;
  const current = result?.version === version ? result : null;

  useEffect(() => {
    const controller = new AbortController();
    api.get("/api/transactions/", {
      params: { ordering: "-timestamp,-id", limit: PAGE_SIZE, offset },
      signal: controller.signal, timeout: 12_000,
    }).then(({ data }) => {
      if (controller.signal.aborted) return;
      if (offset && offset >= data.count) setOffset(Math.max(0, Math.floor((data.count - 1) / PAGE_SIZE) * PAGE_SIZE));
      else setResult({ version, data });
    }).catch(() => {
      if (!controller.signal.aborted) setResult({ version, failed: true });
    });
    return () => controller.abort();
  }, [offset, version]);

  function refresh() {
    setRevision((value) => value + 1);
  }

  async function handleDelete(id) {
    if (deletePending.current) return;
    deletePending.current = true;
    setDeleting(true);
    try {
      await api.delete(`/api/transaction/${id}/`, { timeout: 12_000 });
      setNotice("Transaction deleted.");
      refresh();
    } catch {
      setNotice("Could not delete the transaction. Try again.");
    } finally {
      deletePending.current = false;
      setDeleting(false);
    }
  }

  return (
    <div className="transactions-page">
      <div className="transactions-container">
        <aside className="form-sidebar">
          <TransactionForm onTransactionAdded={() => { setOffset(0); refresh(); }} />
        </aside>
        <main className="transactions-main">
          <div className="transactions-content">
            <p role="status">{notice}</p>
            {!current ? <DashboardLoading label="Loading transactions" /> : current.failed
              ? <DashboardError onRetry={refresh}>Could not load transactions.</DashboardError>
              : current.data.results.length ? <>
                <TransactionList transactions={current.data.results} handleDelete={handleDelete} deleting={deleting} />
                <nav className="transaction-pagination dash-actions" aria-label="Transaction pages">
                  <button type="button" className="dash-button" disabled={!offset}
                    onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Previous</button>
                  <span>{offset + 1}–{offset + current.data.results.length} of {current.data.count}</span>
                  <button type="button" className="dash-button" disabled={!current.data.next}
                    onClick={() => setOffset(offset + PAGE_SIZE)}>Next</button>
                </nav>
              </> : <div><h2>All Transactions</h2><p className="dash-empty">Record a transaction or import a statement to get started.</p></div>}
          </div>
        </main>
      </div>
    </div>
  );
}
