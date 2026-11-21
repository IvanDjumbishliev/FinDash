import { useEffect, useRef, useState } from "react";
import { FiChevronLeft, FiChevronRight, FiPlus } from "react-icons/fi";
import api from "../api";
import BudgetCard from "../components/BudgetCard";
import BudgetEditor from "../components/BudgetEditor";
import BudgetRecommendations from "../components/BudgetRecommendations";
import BudgetSpendingChart from "../components/BudgetSpendingChart";
import { budgetError, budgetTotals, categoryLabel, currentMonth, historicalBudgetTotals, monthLabel, shiftMonth } from "../budgets";
import { formatMoney } from "../subscriptions";
import "../styles/pages/Budgets.css";

const endpoint = "/api/budgets/";
const money = (value, currency) => formatMoney(value, currency);

export default function Budgets() {
  const [month, setMonth] = useState(currentMonth);
  const [overview, setOverview] = useState(null);
  const [history, setHistory] = useState([]);
  const [overviewError, setOverviewError] = useState("");
  const [historyError, setHistoryError] = useState("");
  const [historyLoading, setHistoryLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [selectedId, setSelectedId] = useState(null);
  const [editing, setEditing] = useState(null);
  const [busy, setBusy] = useState(false);
  const [editError, setEditError] = useState("");
  const [notice, setNotice] = useState("");
  const focusTarget = useRef(null);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      setOverviewError("");
      setOverview(null);
      try {
        const { data } = await api.get(`${endpoint}overview/`, {
          params: { period: month }, signal: controller.signal, timeout: 15000,
        });
        if (!Array.isArray(data?.budgets)) throw new Error("Invalid budget overview");
        if (!controller.signal.aborted) setOverview(data);
      } catch (error) {
        if (!controller.signal.aborted) {
          setOverviewError(budgetError(error, "Could not load this month’s budgets."));
        }
      }
    }
    load();
    return () => controller.abort();
  }, [month, revision]);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      setHistoryLoading(true);
      setHistoryError("");
      try {
        const { data } = await api.get(`${endpoint}history/`, { signal: controller.signal, timeout: 15000 });
        if (!Array.isArray(data?.periods)) throw new Error("Invalid budget history");
        if (!controller.signal.aborted) setHistory(data.periods);
      } catch (error) {
        if (!controller.signal.aborted) setHistoryError(budgetError(error, "Could not load budget history."));
      } finally {
        if (!controller.signal.aborted) setHistoryLoading(false);
      }
    }
    load();
    return () => controller.abort();
  }, [revision]);

  function showMonth(period) {
    setSelectedId(null);
    setNotice("");
    setMonth(period.slice(0, 7));
  }

  function openEditor(budget) {
    focusTarget.current = document.activeElement;
    setEditError("");
    setNotice("");
    setEditing({ budget });
  }

  function closeEditor() {
    setEditing(null);
    requestAnimationFrame(() => {
      if (focusTarget.current?.isConnected) focusTarget.current.focus();
    });
  }

  async function changeBudget(action, payload) {
    const budget = editing.budget;
    const url = budget ? `${endpoint}${budget.id}/` : endpoint;
    setBusy(true);
    setEditError("");
    try {
      if (action === "delete") {
        await api.delete(url, { timeout: 15000 });
      } else if (budget) {
        const { data } = await api.patch(url, payload, { timeout: 15000 });
        setMonth(data.period.slice(0, 7));
        setSelectedId(data.id);
      } else {
        const { data } = await api.post(url, payload, { timeout: 15000 });
        setMonth(data.period.slice(0, 7));
        setSelectedId(data.id);
      }
      setRevision((value) => value + 1);
      closeEditor();
      setNotice({
        save: budget ? "Budget updated." : "Budget created.", delete: "Budget deleted.",
        archive: budget?.archived ? "Budget restored." : "Budget archived.",
      }[action]);
    } catch (error) {
      setEditError(budgetError(error, "Could not save the change. Please try again."));
    } finally {
      setBusy(false);
    }
  }

  const current = overview?.period.slice(0, 7) === month ? overview : null;
  const active = current ? [...(current.overall ? [current.overall] : []), ...current.budgets] : [];
  const totals = budgetTotals(active);
  const selectedBudget = active.find(({ id }) => id === selectedId) ?? active[0];
  const archived = (history.find(({ period }) => period.slice(0, 7) === month)?.budgets ?? [])
    .filter((budget) => budget.archived);
  const periods = [
    ...history.filter(({ period }) => period.slice(0, 7) !== month),
    ...(current ? [{ period: current.period, budgets: active }] : []),
  ];
  const months = [...new Set([
    month, ...Array.from({ length: 25 }, (_, i) => shiftMonth(currentMonth(), i - 12)),
    ...history.map(({ period }) => period.slice(0, 7)),
  ])].sort().reverse();

  return (
    <main className="dashboard-shell budget-page">
      <header className="budget-hero">
        <div>
          <h1>Budget planner</h1>
          <p>Set monthly spending limits and see where your money goes.</p>
        </div>
        <button type="button" className="budget-primary" onClick={() => openEditor()}>
          <FiPlus aria-hidden="true" /> New budget
        </button>
      </header>

      <section aria-labelledby="budget-overview-title">
        <div className="budget-heading">
          <h2 id="budget-overview-title">Monthly overview</h2>
          <div className="budget-actions budget-month-controls">
            <button type="button" aria-label="Previous month" disabled={month === "0001-01"}
              onClick={() => showMonth(shiftMonth(month, -1))}><FiChevronLeft aria-hidden="true" /></button>
            <label htmlFor="budget-month" className="budget-sr-only">Budget month</label>
            <select id="budget-month" value={month} onChange={(event) => showMonth(event.target.value)}>
              {months.map((value) => <option value={value} key={value}>{monthLabel(value)}</option>)}
            </select>
            <button type="button" aria-label="Next month" disabled={month === "9999-11"}
              onClick={() => showMonth(shiftMonth(month, 1))}><FiChevronRight aria-hidden="true" /></button>
          </div>
        </div>
        {notice && <p className="budget-feedback" role="status">{notice}</p>}
        {overviewError ? (
          <div className="budget-feedback budget-error">
            <p role="alert">{overviewError}</p>
            <button type="button" onClick={() => setRevision((value) => value + 1)}>Retry overview</button>
          </div>
        ) : !current ? (
          <>
            <p className="budget-muted" role="status">Loading monthly budgets…</p>
            <div className="budget-metrics" aria-hidden="true">
              {[1, 2, 3].map((key) => <div key={key} className="budget-panel budget-skeleton" />)}
            </div>
          </>
        ) : totals.length === 0 ? (
          <div className="budget-panel budget-empty">
            <h3>No active budgets for {monthLabel(month)}</h3>
            <p>Add a category limit or an overall budget to track this month’s spending.</p>
            <button type="button" onClick={() => openEditor()}>Create a budget</button>
          </div>
        ) : (
          <>
            <div className="budget-metrics">
              {[
                ["allocated", "Total allocated budget"], ["spent", "Actual spending"], ["remaining", "Remaining budget"],
              ].map(([field, label]) => (
                <div className="budget-panel budget-metric" key={field}>
                  <h3>{label}</h3>
                  {totals.map((total) => (
                    <p key={total.currency} data-negative={total[field] < 0}>
                      {money(total[field], total.currency)} <small>{total.currency}</small>
                    </p>
                  ))}
                </div>
              ))}
            </div>
            <p className="budget-muted">For each currency, totals use the overall budget when available. Otherwise they cover budgeted categories only.</p>
          </>
        )}
      </section>

      {active.length > 0 && (
        <section aria-labelledby="budget-cards-title">
          <div className="budget-heading"><h2 id="budget-cards-title">Budget breakdown</h2></div>
          <div className="budget-cards">
            {active.map((budget) => (
              <BudgetCard key={budget.id} budget={budget} selected={selectedBudget?.id === budget.id}
                onEdit={openEditor} onView={({ id }) => {
                  setSelectedId(id);
                  requestAnimationFrame(() => document.querySelector(".budget-spending")?.scrollIntoView({ block: "nearest" }));
                }} />
            ))}
          </div>
        </section>
      )}

      <BudgetRecommendations key={month} month={month} onApplied={(count) => {
        setRevision((previous) => previous + 1);
        setNotice(`${count} budget ${count === 1 ? "suggestion" : "suggestions"} applied.`);
      }} />

      <BudgetSpendingChart periods={periods} month={month} budget={selectedBudget} />

      <section className="budget-panel budget-history" aria-labelledby="budget-history-title">
        <h2 id="budget-history-title">Budget utilization history</h2>
        <p className="budget-muted">Spending is calculated from your saved transactions in each month.</p>
        {historyLoading ? <p role="status">Loading budget history…</p> : historyError ? (
          <div className="budget-feedback budget-error">
            <p role="alert">{historyError}</p>
            <button type="button" onClick={() => setRevision((value) => value + 1)}>Retry history</button>
          </div>
        ) : !history.length ? <p>No budget history yet. Saved months will appear here.</p> : (
          <ul className="budget-history-list">
            {history.map(({ period, budgets }) => {
              const monthlyTotals = historicalBudgetTotals(budgets);
              return (
                <li key={period}>
                  <strong>{monthLabel(period)}</strong>
                  <div>
                    {monthlyTotals.map(({ currency, allocated, spent, utilization }) => (
                      <p key={currency}>{money(spent, currency)} of {money(allocated, currency)} · {utilization.toFixed(1)}% used</p>
                    ))}
                    {budgets.every((budget) => budget.archived) && <span className="budget-muted">Archived budgets</span>}
                  </div>
                  <button type="button" onClick={() => showMonth(period)} aria-label={`Open ${monthLabel(period)}`}>Open month</button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {archived.length > 0 && (
        <section className="budget-panel" aria-labelledby="archived-budget-title">
          <h2 id="archived-budget-title">Archived budgets for {monthLabel(month)}</h2>
          <ul className="budget-history-list">
            {archived.map((budget) => (
              <li key={budget.id}>
                <strong>{categoryLabel(budget.category)}</strong>
                <span>{money(budget.amount, budget.currency)} allocated</span>
                <button type="button" onClick={() => openEditor(budget)}>Manage archived budget</button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {editing && <BudgetEditor budget={editing.budget} month={month} busy={busy} error={editError}
        onSave={(payload) => changeBudget("save", payload)}
        onArchive={() => changeBudget("archive", { archived: !editing.budget.archived })}
        onDelete={() => changeBudget("delete")} onClose={closeEditor} />}
    </main>
  );
}
