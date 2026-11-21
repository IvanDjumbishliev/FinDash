import { useEffect, useId, useState } from "react";
import PropTypes from "prop-types";
import { FiArchive, FiCheckCircle, FiClock, FiEdit2, FiPlus, FiRotateCcw, FiTarget } from "react-icons/fi";
import api from "../../api";
import { displayDate, money } from "../../copilotPresentation";
import { goalEndpoint, goalProgress } from "../../financialGoals";

export default function GoalCard({ goal, onAction, celebrating }) {
  const id = useId();
  const [projection, setProjection] = useState(null);
  const [reload, setReload] = useState(0);
  const estimate = !goal.completed && Number(goal.monthly_contribution) > 0;
  const url = `${goalEndpoint(goal.id)}projection/`;
  const version = `${url}:${goal.updated_at}:${reload}`;

  useEffect(() => {
    if (!estimate) return;
    const controller = new AbortController();
    api.get(url, { signal: controller.signal, timeout: 12_000 }).then(({ data }) => {
      if (!controller.signal.aborted) setProjection({ version, data });
    }).catch(() => {
      if (!controller.signal.aborted) setProjection({ version, failed: true });
    });
    return () => controller.abort();
  }, [estimate, url, version]);

  const current = projection?.version === version ? projection : null;
  const projectedDate = displayDate(current?.data?.projected_completion_date);
  const progress = goalProgress(goal);
  return <article className={`goals-card${celebrating ? " goals-celebrating" : ""}`} aria-labelledby={id}>
    {celebrating && <span className="goals-confetti" aria-hidden="true">
      {Array.from({ length: 8 }, (_, index) => <i key={index} style={{ "--piece": index }} />)}
    </span>}
    <header className="goals-card-header">
      <span className="goals-symbol">{goal.completed ? <FiCheckCircle aria-hidden="true" /> : <FiTarget aria-hidden="true" />}</span>
      <div>
        <h3 id={id}>{goal.name}</h3>
        <span className="goals-muted">{goal.currency}</span>
      </div>
      {(goal.archived || goal.completed) && <span className="goals-status">{goal.archived ? "Archived" : "Goal reached"}</span>}
    </header>
    <dl className="goals-card-amounts">
      <div><dt>Saved</dt><dd>{money(goal.current_amount, goal.currency)}</dd></div>
      <div><dt>Target</dt><dd>{money(goal.target_amount, goal.currency)}</dd></div>
    </dl>
    <div className="goals-progress">
      <div className="goals-progress-label"><strong>{progress.label}</strong><span>{money(goal.remaining_amount, goal.currency)} remaining</span></div>
      <progress value={progress.width} max={100} aria-label={`Progress for ${goal.name}`} aria-valuetext={progress.label} />
    </div>
    <dl className="goals-dates">
      <div><dt>Target date</dt><dd>{displayDate(goal.target_date) || "No target date"}</dd></div>
      <div><dt>Estimated completion</dt><dd>
        {goal.completed ? "Reached" : !estimate ? "Set a monthly rate" : !current ? "Calculating…" :
          current.failed ? <button className="goals-text-button" type="button" onClick={() => setReload(reload + 1)}>Retry estimate</button> :
          projectedDate || "Outside calendar range"}
      </dd></div>
    </dl>
    {current?.data?.projected_on_time === false && projectedDate && <p className="goals-muted goals-deadline">Estimated after the target date</p>}
    <div className="goals-actions">
      {!goal.archived && <button type="button" className="goals-primary" onClick={(event) => onAction("contribution", goal, event.currentTarget)}>
        <FiPlus aria-hidden="true" /> Add contribution
      </button>}
      <button type="button" onClick={(event) => onAction("history", goal, event.currentTarget)}><FiClock aria-hidden="true" /> History</button>
      <button type="button" onClick={(event) => onAction("edit", goal, event.currentTarget)}><FiEdit2 aria-hidden="true" /> Edit</button>
      <button type="button" onClick={(event) => onAction("archive", goal, event.currentTarget)}>
        {goal.archived ? <><FiRotateCcw aria-hidden="true" /> Restore</> : <><FiArchive aria-hidden="true" /> Archive</>}
      </button>
    </div>
  </article>;
}

GoalCard.propTypes = {
  goal: PropTypes.shape({
    id: PropTypes.number.isRequired, name: PropTypes.string.isRequired, currency: PropTypes.string.isRequired,
    current_amount: PropTypes.string.isRequired, target_amount: PropTypes.string.isRequired, remaining_amount: PropTypes.string,
    target_date: PropTypes.string, monthly_contribution: PropTypes.string, updated_at: PropTypes.string.isRequired,
    archived: PropTypes.bool, completed: PropTypes.bool,
  }).isRequired,
  onAction: PropTypes.func.isRequired,
  celebrating: PropTypes.bool,
};
