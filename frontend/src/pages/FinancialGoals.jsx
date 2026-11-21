import { useEffect, useRef, useState } from "react";
import { FiPlus, FiTarget } from "react-icons/fi";
import api from "../api";
import GoalCard from "../components/goals/GoalCard";
import GoalHistory from "../components/goals/GoalHistory";
import { ArchiveGoalDialog, ContributionDialog, GoalEditor } from "../components/goals/GoalDialogs";
import { formatGoalTotal, goalEndpoint, goalError, goalsEndpoint, summarizeGoals } from "../financialGoals";
import "../styles/pages/FinancialGoals.css";

export default function FinancialGoals() {
  const [goals, setGoals] = useState([]);
  const [view, setView] = useState("current");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [dialog, setDialog] = useState(null);
  const [notice, setNotice] = useState("");
  const [celebration, setCelebration] = useState(null);
  const opener = useRef(null);
  const heading = useRef(null);

  useEffect(() => {
    const controller = new AbortController();
    api.get(goalsEndpoint, { signal: controller.signal, timeout: 12_000 }).then(({ data }) => {
      if (!Array.isArray(data)) throw new Error("Unexpected goals response.");
      if (!controller.signal.aborted) setGoals(data);
    }).catch((failure) => {
      if (!controller.signal.aborted) setError(goalError(failure, "Could not load your goals."));
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [reload]);

  useEffect(() => {
    if (celebration === null) return;
    const timer = setTimeout(() => setCelebration(null), 1500);
    return () => clearTimeout(timer);
  }, [celebration]);

  function open(kind, goal, trigger) {
    opener.current = trigger;
    setNotice("");
    setDialog({ kind, goal });
  }

  function close() {
    const trigger = opener.current;
    setDialog(null);
    requestAnimationFrame(() => (trigger?.isConnected ? trigger : heading.current)?.focus());
  }

  function update(goal) {
    setGoals((previous) => previous.map((item) => item.id === goal.id ? goal : item));
  }

  async function save(payload, goal) {
    const config = { timeout: 12_000 };
    if (goal) {
      const { data } = await api.patch(goalEndpoint(goal.id), payload, config);
      update(data);
      setNotice(payload.archived === true ? "Goal archived." : payload.archived === false ? "Goal restored." : "Goal updated.");
    } else {
      const { data } = await api.post(goalsEndpoint, payload, config);
      setGoals((previous) => [data, ...previous]);
      setView("current");
      setNotice("Savings goal created.");
    }
    close();
  }

  function recorded(goal, before, kind) {
    update(goal);
    if (kind === "contribution" && goal.completed && !before.completed) {
      setCelebration(goal.id);
      setNotice(`Goal reached: ${goal.name}.`);
    } else {
      setNotice(kind === "withdrawal" ? "Withdrawal recorded." : "Contribution recorded.");
    }
    close();
  }

  const totals = summarizeGoals(goals);
  const current = goals.filter((goal) => !goal.archived);
  const archived = goals.filter((goal) => goal.archived);
  const shown = view === "archived" ? archived : current;

  return <main className="goals-page">
    <header className="goals-page-header">
      <div className="goals-page-title">
        <span className="goals-symbol"><FiTarget aria-hidden="true" /></span>
        <div><h1 ref={heading} tabIndex={-1}>Financial Goals</h1><p>Plan what you’re saving for and track each contribution.</p></div>
      </div>
      <button type="button" className="goals-primary" disabled={loading || Boolean(error)}
        onClick={(event) => open("create", null, event.currentTarget)}><FiPlus aria-hidden="true" /> New goal</button>
    </header>

    {loading && <div className="goals-callout" role="status">Loading your goals…</div>}
    {error && <div className="goals-callout">
      <p role="alert">{error}</p>
      <button type="button" onClick={() => { setLoading(true); setError(""); setReload(reload + 1); }}>Retry</button>
    </div>}
    {!loading && !error && <>
      {totals.length > 0 && <section className="goals-summary" aria-labelledby="goals-summary-heading">
        <h2 id="goals-summary-heading">Savings summary</h2>
        <p className="goals-muted">Totals cover unarchived goals. Net contributions are deposits minus withdrawals recorded in your goal ledger.</p>
        <div className="goals-summary-grid">
          {totals.map((total) => <div className="goals-summary-row" key={total.currency}>
            <h3>{total.currency}</h3>
            <dl>
              <div><dt>Total goal targets</dt><dd>{formatGoalTotal(total.target, total.currency)}</dd></div>
              <div><dt>Net recorded contributions</dt><dd>{formatGoalTotal(total.saved, total.currency)}</dd></div>
            </dl>
          </div>)}
        </div>
      </section>}
      <section className="goals-section" aria-labelledby="goals-list-heading">
        <div className="goals-section-heading">
          <h2 id="goals-list-heading">Your goals</h2>
          <div className="goals-filter" aria-label="Filter goals" role="group">
            <button type="button" aria-pressed={view === "current"} onClick={() => setView("current")}>Current ({current.length})</button>
            <button type="button" aria-pressed={view === "archived"} onClick={() => setView("archived")}>Archived ({archived.length})</button>
          </div>
        </div>
        <p className="goals-notice" role="status">{notice}</p>
        {shown.length > 0 ? <div className="goals-grid">
          {shown.map((goal) => <GoalCard key={goal.id} goal={goal} onAction={open} celebrating={celebration === goal.id} />)}
        </div> : <div className="goals-callout goals-empty">
          <FiTarget aria-hidden="true" />
          <h3>{view === "archived" ? "No archived goals" : "No current goals"}</h3>
          <p>{view === "archived" ? "Archived goals and their contribution history appear here." : "Create a savings goal to start tracking your progress."}</p>
        </div>}
      </section>
    </>}

    {(dialog?.kind === "create" || dialog?.kind === "edit") && <GoalEditor goal={dialog.goal} onClose={close} onSave={save} />}
    {dialog?.kind === "contribution" && <ContributionDialog goal={dialog.goal} onClose={close} onRecorded={recorded} />}
    {dialog?.kind === "history" && <GoalHistory goal={dialog.goal} onClose={close} />}
    {dialog?.kind === "archive" && <ArchiveGoalDialog goal={dialog.goal} onClose={close} onSave={save} />}
  </main>;
}
