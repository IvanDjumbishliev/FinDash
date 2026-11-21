import { useState } from "react";
import PropTypes from "prop-types";
import { budgetCategories, categoryLabel } from "../budgets";
import { formatMoney } from "../subscriptions";
import { bulkReviewChanges, isPossibleDuplicate } from "../statementReview";

const pageSize = 25;
const sources = {
  built_in_rule: "Built-in rule", user_rule: "Your rule", statement: "Statement",
  manual: "Manual correction", ai: "Gemini suggestion", unclassified: "Unclassified",
};

function ReviewRow({ row, selected, busy, onSelect, onCorrect }) {
  const [merchant, setMerchant] = useState(row.merchant);
  const [category, setCategory] = useState(row.category);
  const hasChanges = merchant.trim() !== row.merchant || category !== row.category;

  function save(event) {
    event.preventDefault();
    const change = { row_id: row.row_id };
    if (merchant.trim() !== row.merchant) change.merchant = merchant.trim();
    if (category !== row.category) change.category = category;
    onCorrect(change);
  }

  return (
    <li className="statement-review-row">
      <div className="statement-review-heading">
        <label><input type="checkbox" checked={selected} disabled={busy} onChange={onSelect} /> Row {row.row_id}</label>
        <strong>{formatMoney(row.amount, row.currency)}</strong>
      </div>
      <p>{row.timestamp.slice(0, 10)} · {row.particulars}</p>
      {row.reference && <p className="statement-muted">Reference {row.reference}</p>}
      <p className="statement-muted">
        {sources[row.category_source]} · {Math.round(row.category_confidence * 100)}% confidence
        {" · "}{row.decision === "pending" ? "Needs review" : row.decision === "rejected" ? "Rejected" : "Approved"}
      </p>
      {isPossibleDuplicate(row) && (
        <p className="statement-duplicate">
          Possible duplicate
          {row.duplicate_matches.existing.length > 0 && " · Matches a saved transaction"}
          {row.duplicate_matches.file.length > 0 && " · Matches another row in this file"}
        </p>
      )}
      <form className="statement-correction" onSubmit={save}>
        <label>Merchant for row {row.row_id}
          <input value={merchant} onChange={(event) => setMerchant(event.target.value)}
            maxLength={255} required disabled={busy} />
        </label>
        <label>Category for row {row.row_id}
          <select value={category} onChange={(event) => setCategory(event.target.value)} disabled={busy}>
            {budgetCategories.map((option) => <option key={option} value={option}>{categoryLabel(option)}</option>)}
          </select>
        </label>
        <button type="submit" disabled={busy || !hasChanges}>Save correction</button>
      </form>
    </li>
  );
}

ReviewRow.propTypes = {
  row: PropTypes.shape({
    row_id: PropTypes.number.isRequired, merchant: PropTypes.string.isRequired,
    category: PropTypes.string.isRequired, amount: PropTypes.string.isRequired,
    currency: PropTypes.string.isRequired, timestamp: PropTypes.string.isRequired,
    particulars: PropTypes.string.isRequired, reference: PropTypes.string,
    category_source: PropTypes.string.isRequired, category_confidence: PropTypes.number.isRequired,
    decision: PropTypes.string.isRequired, duplicate_matches: PropTypes.object.isRequired,
  }).isRequired,
  selected: PropTypes.bool.isRequired,
  busy: PropTypes.bool.isRequired,
  onSelect: PropTypes.func.isRequired,
  onCorrect: PropTypes.func.isRequired,
};

export default function StatementReview({ rows, busy, onReview }) {
  const [page, setPage] = useState(0);
  const [selection, setSelection] = useState({});
  const [allowDuplicates, setAllowDuplicates] = useState(false);
  const [pendingAction, setPendingAction] = useState("");
  const selected = rows.filter((row) => selection[row.row_id]);
  const selectedDuplicates = selected.some(isPossibleDuplicate);
  const pageRows = rows.slice(page * pageSize, (page + 1) * pageSize);
  const pages = Math.ceil(rows.length / pageSize);

  async function decide(decision) {
    const changes = bulkReviewChanges(selected, decision, allowDuplicates);
    if (!changes.length) return;
    setPendingAction(decision);
    const saved = await onReview(changes);
    setPendingAction("");
    if (saved) {
      setSelection({});
      setAllowDuplicates(false);
    }
  }

  return (
    <section aria-label="Statement preview">
      <h3>Preview · {rows.length} {rows.length === 1 ? "transaction" : "transactions"}</h3>
      <p>Only approved rows will be saved. Review possible duplicates and Gemini suggestions before approving them.</p>
      <div className="statement-actions">
        <button type="button" disabled={busy} onClick={() => {
          setAllowDuplicates(false);
          setSelection((previous) => ({
            ...previous, ...Object.fromEntries(pageRows.map((row) => [row.row_id, true])),
          }));
        }}>Select this page</button>
        <button type="button" disabled={busy || !selected.length} onClick={() => { setSelection({}); setAllowDuplicates(false); }}>Clear selection</button>
        <span role="status">{selected.length} selected</span>
      </div>
      {selectedDuplicates && <label className="statement-consent">
        <input type="checkbox" disabled={busy} checked={allowDuplicates} onChange={(event) => setAllowDuplicates(event.target.checked)} />
        Keep selected possible duplicates after review.
      </label>}
      <div className="statement-actions">
        <button type="button" disabled={busy || !selected.length || (selectedDuplicates && !allowDuplicates)}
          onClick={() => decide("approved")}>{pendingAction === "approved" ? "Approving…" : "Approve selected"}</button>
        <button type="button" disabled={busy || !selected.length} onClick={() => decide("rejected")}>
          {pendingAction === "rejected" ? "Rejecting…" : "Reject selected"}
        </button>
      </div>
      <div className="statement-table" tabIndex={0} role="region" aria-label="Parsed transactions">
        <ul className="statement-review-list">
          {pageRows.map((row) => (
            <ReviewRow key={`${row.row_id}:${row.merchant}:${row.category}`} row={row}
              selected={Boolean(selection[row.row_id])} busy={busy}
              onSelect={() => {
                setSelection((previous) => ({ ...previous, [row.row_id]: !previous[row.row_id] }));
                setAllowDuplicates(false);
              }}
              onCorrect={(change) => onReview([change])} />
          ))}
        </ul>
      </div>
      {pages > 1 && <div className="statement-actions">
        <button type="button" disabled={page === 0 || busy} onClick={() => setPage((value) => value - 1)}>Previous</button>
        <span>Page {page + 1} of {pages}</span>
        <button type="button" disabled={page + 1 === pages || busy} onClick={() => setPage((value) => value + 1)}>Next</button>
      </div>}
    </section>
  );
}

StatementReview.propTypes = {
  rows: PropTypes.arrayOf(PropTypes.object).isRequired,
  busy: PropTypes.bool.isRequired,
  onReview: PropTypes.func.isRequired,
};
