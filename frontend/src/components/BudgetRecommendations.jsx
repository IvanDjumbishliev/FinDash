import { useEffect, useRef, useState } from "react";
import PropTypes from "prop-types";
import api from "../api";
import { budgetError, categoryLabel, monthLabel } from "../budgets";
import { recommendationRequest, reviewPayload } from "../budgetRecommendations";
import { formatMoney } from "../subscriptions";

const endpoint = "/api/budgets/recommendations/";

function ApprovalDialog({ count, month, busy, error, onClose, onConfirm }) {
  const dialog = useRef(null);
  useEffect(() => {
    const element = dialog.current;
    element.showModal();
    return () => element.close();
  }, []);

  return (
    <dialog ref={dialog} className="budget-dialog budget-approval" aria-labelledby="budget-approval-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onClose();
      }}>
      <h2 id="budget-approval-title">Apply {count} selected {count === 1 ? "suggestion" : "suggestions"}?</h2>
      <p>The selected category limits for {monthLabel(month)} will be created or updated.</p>
      {error && <p role="alert" className="budget-feedback budget-error">{error}</p>}
      <div className="budget-actions">
        <button type="button" disabled={busy} onClick={onClose}>Go back</button>
        <button type="button" className="budget-primary" disabled={busy} onClick={onConfirm}>
          {busy ? "Applying…" : "Confirm and apply"}
        </button>
      </div>
    </dialog>
  );
}

ApprovalDialog.propTypes = {
  count: PropTypes.number.isRequired,
  month: PropTypes.string.isRequired,
  busy: PropTypes.bool.isRequired,
  error: PropTypes.string,
  onClose: PropTypes.func.isRequired,
  onConfirm: PropTypes.func.isRequired,
};

export default function BudgetRecommendations({ month, onApplied }) {
  const [consent, setConsent] = useState(false);
  const [review, setReview] = useState(null);
  const [choices, setChoices] = useState({});
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [applyError, setApplyError] = useState("");
  const [confirming, setConfirming] = useState(false);
  const request = useRef(null);
  useEffect(() => () => request.current?.abort(), []);

  async function generate() {
    const controller = new AbortController();
    request.current = controller;
    setBusy("generate");
    setError("");
    setReview(null);
    setChoices({});
    setConsent(false);
    try {
      const { data } = await api.post(endpoint, recommendationRequest(month, consent), {
        signal: controller.signal, timeout: 25000,
      });
      if (!Array.isArray(data?.recommendations)) throw new Error("Invalid recommendation response");
      if (!controller.signal.aborted) setReview(data);
    } catch (failure) {
      if (!controller.signal.aborted) setError(budgetError(failure, "Could not generate suggestions. Try again."));
    } finally {
      if (!controller.signal.aborted) setBusy("");
    }
  }

  async function apply() {
    const payload = reviewPayload(review, choices, confirming);
    if (!payload) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy("apply");
    setApplyError("");
    try {
      const { data } = await api.post(`${endpoint}apply/`, payload, { signal: controller.signal, timeout: 15000 });
      if (!controller.signal.aborted) {
        setReview(null);
        setChoices({});
        setConfirming(false);
        onApplied(data.applied.length);
      }
    } catch (failure) {
      if (!controller.signal.aborted) setApplyError(budgetError(failure, "Could not apply suggestions. Try again."));
    } finally {
      if (!controller.signal.aborted) setBusy("");
    }
  }

  const suggestions = review?.recommendations ?? [];
  const acceptedCount = suggestions.filter(({ category }) => choices[category] === "accepted").length;

  return (
    <section className="budget-panel budget-recommendations" aria-labelledby="budget-recommendations-title">
      <div className="budget-heading">
        <div>
          <h2 id="budget-recommendations-title">Budget suggestions</h2>
          <p className="budget-muted">Review estimates from up to six completed months before choosing which limits to change.</p>
        </div>
        <button type="button" disabled={Boolean(busy)} onClick={generate}>
          {busy === "generate" ? "Analyzing spending…" : "Generate Budget Suggestions"}
        </button>
      </div>
      <label className="budget-consent">
        <input type="checkbox" checked={consent} disabled={Boolean(busy)}
          onChange={(event) => setConsent(event.target.checked)} />
        <span>For this run, allow FinDash to send category names, currencies, suggested amounts, and aggregate spending statistics to Google Gemini for an optional explanation.</span>
      </label>
      {error && <p role="alert" className="budget-feedback budget-error">{error}</p>}
      {busy === "generate" && <p role="status" className="budget-muted">Analyzing completed months…</p>}
      {review?.status === "insufficient_history" && (
        <p role="status" className="budget-feedback">No suggestions yet. A category needs spending in at least three completed months in the same currency.</p>
      )}
      {["unavailable", "not_configured"].includes(review?.ai_status) && (
        <p role="status" className="budget-feedback">Gemini explanations are unavailable. The statistical suggestions are ready to review.</p>
      )}
      {suggestions.length > 0 && (
        <>
          <div className="budget-cards">
            {suggestions.map((item) => {
              const choice = choices[item.category];
              const statistics = item.statistics;
              const amount = (value) => formatMoney(value, item.currency);
              return (
                <article className="budget-panel budget-card budget-suggestion" key={item.category}>
                  <div className="budget-card-heading">
                    <h3>{categoryLabel(item.category)}</h3>
                    {choice && <span className="budget-muted">{choice === "accepted" ? "Selected" : "Rejected"}</span>}
                  </div>
                  <p className="budget-card-amount"><strong>{amount(item.suggested_amount)}</strong> <span>suggested</span></p>
                  <p className="budget-muted">{item.current_amount === null
                    ? "No active budget for this category."
                    : `Current limit ${amount(item.current_amount)}`}</p>
                  <p>{item.explanation}</p>
                  <dl className="budget-suggestion-stats">
                    <div><dt>Months analyzed</dt><dd>{statistics.months_analyzed}</dd></div>
                    <div><dt>Monthly average</dt><dd>{amount(statistics.average)}</dd></div>
                    <div><dt>Monthly variability</dt><dd>{amount(statistics.standard_deviation)}</dd></div>
                    <div><dt>Variability buffer</dt><dd>{amount(statistics.variability_buffer)}</dd></div>
                  </dl>
                  {statistics.trend === "increasing" && <p className="budget-state">Sustained spending increase</p>}
                  {item.ai_explanation && <p className="budget-muted"><strong>Gemini explanation</strong> {item.ai_explanation}</p>}
                  <div className="budget-actions">
                    <button type="button" aria-pressed={choice === "accepted"}
                      aria-label={`Accept suggestion for ${categoryLabel(item.category)}`}
                      onClick={() => setChoices((previous) => ({
                        ...previous, [item.category]: choice === "accepted" ? undefined : "accepted",
                      }))}>Accept</button>
                    <button type="button" aria-pressed={choice === "rejected"}
                      aria-label={`Reject suggestion for ${categoryLabel(item.category)}`}
                      onClick={() => setChoices((previous) => ({
                        ...previous, [item.category]: choice === "rejected" ? undefined : "rejected",
                      }))}>Reject</button>
                  </div>
                </article>
              );
            })}
          </div>
          <div className="budget-actions budget-review-actions">
            <button type="button" className="budget-primary" disabled={!acceptedCount || Boolean(busy)}
              onClick={() => { setApplyError(""); setConfirming(true); }}>
              Apply Selected Suggestions
            </button>
            <p className="budget-muted" role="status">{acceptedCount} selected. Changes require confirmation.</p>
          </div>
        </>
      )}
      {confirming && <ApprovalDialog count={acceptedCount} month={month} busy={busy === "apply"} error={applyError}
        onClose={() => setConfirming(false)} onConfirm={apply} />}
    </section>
  );
}

BudgetRecommendations.propTypes = {
  month: PropTypes.string.isRequired,
  onApplied: PropTypes.func.isRequired,
};
