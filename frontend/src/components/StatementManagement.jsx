import { useEffect, useRef, useState } from "react";
import PropTypes from "prop-types";
import api from "../api";
import { budgetCategories, categoryLabel } from "../budgets";
import { formatMoney } from "../subscriptions";

const root = "/api/bank-statement/";
const limit = 25;
const labels = {
  imported: "Imported", ready: "Ready for review", failed: "Failed", expired: "Expired",
  needs_mapping: "Needs mapping", discarded: "Discarded",
};

function History() {
  const [history, setHistory] = useState(null);
  const [offset, setOffset] = useState(0);
  const [problem, setProblem] = useState("");
  const [selected, setSelected] = useState(null);
  const [transactions, setTransactions] = useState(null);
  const [rowOffset, setRowOffset] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api.get(`${root}imports/`, { params: { limit, offset }, signal: controller.signal })
      .then(({ data }) => setHistory(data))
      .catch(() => { if (!controller.signal.aborted) setProblem("Could not load import history."); });
    return () => controller.abort();
  }, [offset]);

  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    api.get(`${root}imports/${selected}/transactions/`, { params: { limit, offset: rowOffset }, signal: controller.signal })
      .then(({ data }) => setTransactions(data))
      .catch(() => { if (!controller.signal.aborted) setProblem("Could not load imported transactions."); });
    return () => controller.abort();
  }, [selected, rowOffset]);

  function historyPage(next) {
    setHistory(null);
    setProblem("");
    setSelected(null);
    setOffset(next);
  }

  function transactionPage(id, next) {
    setTransactions(null);
    setProblem("");
    setSelected(id);
    setRowOffset(next);
  }

  return (
    <section aria-label="Import history">
      {problem && <p role="alert" className="statement-error">{problem}</p>}
      {!history && !problem && <p role="status">Loading imports…</p>}
      {history?.results.length === 0 && <p>No statement imports yet.</p>}
      <ul className="statement-review-list">
        {history?.results.map((item) => (
          <li key={item.id} className="statement-review-row">
            <strong>{item.file_format.toUpperCase() || "Statement"} · {labels[item.status]}</strong>
            <p>{new Date(item.created_at).toLocaleString()} · {item.imported_count} saved of {item.row_count} parsed</p>
            {item.errors.length > 0 && <details><summary>Parsing errors</summary>
              <ul className="statement-errors">{item.errors.map(({ row, message }, index) =>
                <li key={index}>{row && `Row ${row}. `}{message}</li>)}</ul>
            </details>}
            {item.status === "imported" && (
              <button type="button" onClick={() => selected === item.id
                ? setSelected(null) : transactionPage(item.id, 0)} aria-expanded={selected === item.id}>
                {selected === item.id ? "Hide transactions" : "View transactions"}
              </button>
            )}
            {selected === item.id && (
              <div className="statement-history-details">
                {!transactions && !problem && <p role="status">Loading imported transactions…</p>}
                {transactions?.results.length === 0 && <p>No linked transactions are available for this import.</p>}
                <ul className="statement-review-list">
                  {transactions?.results.map((row) => (
                    <li key={row.id}>{row.timestamp.slice(0, 10)} · {row.merchant} · {categoryLabel(row.category)}
                      {" · "}{formatMoney(row.amount, row.currency)}</li>
                  ))}
                </ul>
                <div className="statement-actions">
                  {transactions?.previous && <button type="button" onClick={() => transactionPage(item.id, rowOffset - limit)}>Previous transactions</button>}
                  {transactions?.next && <button type="button" onClick={() => transactionPage(item.id, rowOffset + limit)}>Next transactions</button>}
                </div>
              </div>
            )}
          </li>
        ))}
      </ul>
      <div className="statement-actions">
        {history?.previous && <button type="button" onClick={() => historyPage(offset - limit)}>Previous imports</button>}
        {history?.next && <button type="button" onClick={() => historyPage(offset + limit)}>Next imports</button>}
      </div>
    </section>
  );
}

function Rules() {
  const [rules, setRules] = useState(null);
  const [edit, setEdit] = useState(null);
  const [merchant, setMerchant] = useState("");
  const [category, setCategory] = useState("general");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    api.get(`${root}rules/`, { signal: controller.signal })
      .then(({ data }) => setRules(data))
      .catch(() => { if (!controller.signal.aborted) setError("Could not load categorization rules."); });
    return () => controller.abort();
  }, []);

  function fill(rule) {
    setEdit(rule?.id ?? null);
    setMerchant(rule?.merchant ?? "");
    setCategory(rule?.category ?? "general");
    setError("");
  }

  async function save(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const fields = { merchant, category };
      const { data } = edit
        ? await api.patch(`${root}rules/${edit}/`, fields)
        : await api.post(`${root}rules/`, fields);
      setRules((previous) => [...(previous ?? []).filter((rule) => rule.id !== data.id), data]);
      fill(null);
      setNotice("Rule saved.");
    } catch (failure) {
      const message = failure.response?.data?.merchant;
      setError(Array.isArray(message) ? message.join(" ") : "Could not save the categorization rule.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(rule) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api.delete(`${root}rules/${rule.id}/`);
      setRules((previous) => previous.filter(({ id }) => id !== rule.id));
      if (edit === rule.id) fill(null);
      setNotice("Rule removed.");
    } catch {
      setError("Could not remove the rule.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label="Categorization rules">
      <p>Rules match normalized merchant names in future imports.</p>
      <form className="statement-correction" onSubmit={save}>
        <label>Rule merchant<input value={merchant} onChange={(event) => setMerchant(event.target.value)} required maxLength={255} disabled={busy} /></label>
        <label>Rule category<select value={category} onChange={(event) => setCategory(event.target.value)} disabled={busy}>
          {budgetCategories.map((option) => <option key={option} value={option}>{categoryLabel(option)}</option>)}
        </select></label>
        <button disabled={busy} type="submit">{edit ? "Update rule" : "Add rule"}</button>
        {edit && <button disabled={busy} type="button" onClick={() => fill(null)}>Cancel edit</button>}
      </form>
      {error && <p role="alert" className="statement-error">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {!rules && !error && <p role="status">Loading rules…</p>}
      {rules?.length === 0 && <p>No rules yet.</p>}
      <ul className="statement-review-list">
        {rules?.map((rule) => (
          <li className="statement-review-row" key={rule.id}>
            <p><strong>{rule.merchant}</strong> · {categoryLabel(rule.category)}</p>
            <div className="statement-actions">
              <button type="button" disabled={busy} onClick={() => fill(rule)}>Edit rule</button>
              <button type="button" disabled={busy} onClick={() => remove(rule)}>Remove rule</button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function StatementManagement({ initialView, onClose }) {
  const modal = useRef(null);
  const [view, setView] = useState(initialView);
  useEffect(() => {
    const dialog = modal.current;
    dialog.showModal();
    return () => dialog.close();
  }, []);

  return (
    <dialog className="statement-dialog" ref={modal} aria-labelledby="statement-management-title"
      onCancel={(event) => { event.preventDefault(); onClose(); }}>
      <h2 id="statement-management-title">Statement imports</h2>
      <div className="statement-actions" role="group" aria-label="Manage statements">
        <button type="button" aria-pressed={view === "history"} onClick={() => setView("history")}>Import history</button>
        <button type="button" aria-pressed={view === "rules"} onClick={() => setView("rules")}>Categorization rules</button>
      </div>
      {view === "history" ? <History /> : <Rules />}
      <button type="button" onClick={onClose}>Close</button>
    </dialog>
  );
}

StatementManagement.propTypes = {
  initialView: PropTypes.oneOf(["history", "rules"]).isRequired,
  onClose: PropTypes.func.isRequired,
};
