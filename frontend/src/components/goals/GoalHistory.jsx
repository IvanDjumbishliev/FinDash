import { useEffect, useState } from "react";
import PropTypes from "prop-types";
import api from "../../api";
import { money } from "../../copilotPresentation";
import { goalEndpoint, goalError } from "../../financialGoals";
import { GoalDialog } from "./GoalDialogs";

const PAGE_SIZE = 10;
const timestamp = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

export default function GoalHistory({ goal, onClose }) {
  const [offset, setOffset] = useState(0);
  const [reload, setReload] = useState(0);
  const [page, setPage] = useState(null);
  const key = `${goal.id}:${offset}:${reload}`;

  useEffect(() => {
    const controller = new AbortController();
    api.get(`${goalEndpoint(goal.id)}contributions/`, {
      params: { limit: PAGE_SIZE, offset }, signal: controller.signal, timeout: 12_000,
    }).then(({ data }) => {
      if (!controller.signal.aborted) setPage({ key, data });
    }).catch((error) => {
      if (!controller.signal.aborted) setPage({ key, error: goalError(error, "Could not load contributions.") });
    });
    return () => controller.abort();
  }, [goal.id, key, offset]);

  const current = page?.key === key ? page : null;
  const data = current?.data;

  return <GoalDialog title="Contribution history" onClose={onClose}>
    <p className="goals-muted">{goal.name} · {goal.currency}</p>
    {!current && <p className="goals-callout" role="status">Loading history…</p>}
    {current?.error && <div className="goals-callout">
      <p role="alert">{current.error}</p>
      <button type="button" onClick={() => setReload(reload + 1)}>Retry</button>
    </div>}
    {data && (data.results.length === 0 ? <p className="goals-callout">No activity recorded yet.</p> :
      <ul className="goals-ledger">
        {data.results.map((entry) => <li key={entry.id}>
          <div>
            <strong>{entry.kind === "withdrawal" ? "Withdrawal" : "Contribution"}</strong>
            <time dateTime={entry.created_at}>{timestamp.format(new Date(entry.created_at))}</time>
            {entry.note && <p>{entry.note}</p>}
          </div>
          <div>
            <strong>{entry.kind === "withdrawal" ? "−" : "+"}{money(entry.amount, entry.currency)}</strong>
            <span>Saved after entry {money(entry.balance_after, entry.currency)}</span>
          </div>
        </li>)}
      </ul>)}
    {(offset > 0 || data?.next) && <nav className="goals-ledger-pages" aria-label="Contribution history pages">
      <button type="button" disabled={!offset} onClick={() => setOffset(offset - PAGE_SIZE)}>Previous</button>
      <span aria-live="polite">{data?.results.length > 0 && `${offset + 1}–${offset + data.results.length} of ${data.count}`}</span>
      <button type="button" disabled={!data?.next} onClick={() => setOffset(offset + PAGE_SIZE)}>Next</button>
    </nav>}
  </GoalDialog>;
}

GoalHistory.propTypes = {
  goal: PropTypes.shape({ id: PropTypes.number.isRequired, name: PropTypes.string.isRequired, currency: PropTypes.string.isRequired }).isRequired,
  onClose: PropTypes.func.isRequired,
};
