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
const decisions = { pending: "Needs review", approved: "Approved", rejected: "Excluded" };

export default function StatementReview({ rows, busy, onReview, onNext, onBack }) {
  const [page, setPage] = useState(0);
  const [selection, setSelection] = useState({});
  const [drafts, setDrafts] = useState({});
  const [allowDuplicates, setAllowDuplicates] = useState(false);
  const selected = rows.filter((row) => selection[row.row_id]);
  const selectedDuplicates = selected.some(isPossibleDuplicate);
  const pageRows = rows.slice(page * pageSize, (page + 1) * pageSize);
  const pages = Math.ceil(rows.length / pageSize);
  const dirty = Object.keys(drafts).length > 0;
  const approvalCount = rows.filter(({ decision }) => decision === "approved").length;

  function change(row, field, value) {
    setDrafts((previous) => {
      const next = { ...previous };
      const draft = { ...next[row.row_id], [field]: value };
      if (row[field] === value) delete draft[field];
      if (Object.keys(draft).length) next[row.row_id] = draft;
      else delete next[row.row_id];
      return next;
    });
  }

  async function saveCorrections() {
    const changes = Object.entries(drafts).map(([id, draft]) => ({
      ...draft,
      ...(draft.merchant === undefined ? {} : { merchant: draft.merchant.trim() }),
      row_id: Number(id),
    }));
    if (await onReview(changes)) setDrafts({});
  }

  async function decide(decision) {
    const changes = bulkReviewChanges(selected, decision, allowDuplicates);
    if (changes.length && await onReview(changes)) clearSelection();
  }

  function clearSelection() {
    setSelection({});
    setAllowDuplicates(false);
  }

  return (
    <section aria-label="Statement preview">
      <p>Correct merchants or categories, then save your corrections. Only approved rows will be imported.</p>
      <div className="statement-actions">
        <button type="button" disabled={busy} onClick={() => {
          setAllowDuplicates(false);
          setSelection((previous) => ({
            ...previous, ...Object.fromEntries(pageRows.map((row) => [row.row_id, true])),
          }));
        }}>Select this page</button>
        <button type="button" disabled={busy || !selected.length} onClick={clearSelection}>Clear selection</button>
        <button type="button" disabled={busy || dirty || !selected.length || (selectedDuplicates && !allowDuplicates)}
          onClick={() => decide("approved")}>Approve selected</button>
        <button type="button" disabled={busy || dirty || !selected.length} onClick={() => decide("rejected")}>Exclude selected</button>
        <span role="status">{selected.length} selected for review</span>
      </div>
      {selectedDuplicates && <label className="statement-consent">
        <input type="checkbox" disabled={busy} checked={allowDuplicates} onChange={(event) => setAllowDuplicates(event.target.checked)} />
        Keep selected possible duplicates after review.
      </label>}
      <p className="statement-muted">Scroll the table to see all columns on smaller screens.</p>
      <div className="statement-table" tabIndex={0} role="region" aria-label="Parsed transactions">
        <table>
          <thead><tr>
            <th scope="col">Row</th><th scope="col">Date and description</th><th scope="col">Amount</th>
            <th scope="col">Merchant</th><th scope="col">Category</th><th scope="col">Review status</th>
          </tr></thead>
          <tbody>
            {pageRows.map((row) => (
              <tr key={row.row_id}>
                <th scope="row"><label>
                  <input type="checkbox" checked={Boolean(selection[row.row_id])} disabled={busy}
                    onChange={(event) => {
                      const checked = event.target.checked;
                      setSelection((previous) => ({ ...previous, [row.row_id]: checked }));
                      setAllowDuplicates(false);
                    }} /> {row.row_id}
                  <span className="statement-visually-hidden">Select row {row.row_id}</span>
                </label></th>
                <td>
                  <time dateTime={row.timestamp}>{row.timestamp.slice(0, 10)}</time>
                  <p>{row.particulars}</p>
                  {row.reference && <p className="statement-muted">Reference {row.reference}</p>}
                </td>
                <td>{formatMoney(row.amount, row.currency)}</td>
                <td><input aria-label={`Merchant for row ${row.row_id}`} name={`merchant-${row.row_id}`}
                  value={drafts[row.row_id]?.merchant ?? row.merchant} maxLength={255} disabled={busy}
                  onChange={(event) => change(row, "merchant", event.target.value)} /></td>
                <td>
                  <select aria-label={`Category for row ${row.row_id}`} name={`category-${row.row_id}`}
                    value={drafts[row.row_id]?.category ?? row.category} disabled={busy}
                    onChange={(event) => change(row, "category", event.target.value)}>
                    {budgetCategories.map((category) => <option key={category} value={category}>{categoryLabel(category)}</option>)}
                  </select>
                  <p className="statement-muted">{sources[row.category_source]} · {Math.round(row.category_confidence * 100)}% confidence</p>
                </td>
                <td>
                  <strong>{decisions[row.decision]}</strong>
                  {isPossibleDuplicate(row) && <p className="statement-duplicate">
                    Possible duplicate
                    {row.duplicate_matches.existing.length > 0 && " · Saved transaction"}
                    {row.duplicate_matches.file.length > 0 && " · Another row in this file"}
                  </p>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {pages > 1 && <div className="statement-actions">
        <button type="button" disabled={page === 0 || busy} onClick={() => setPage((value) => value - 1)}>Previous rows</button>
        <span>Page {page + 1} of {pages}</span>
        <button type="button" disabled={page + 1 === pages || busy} onClick={() => setPage((value) => value + 1)}>Next rows</button>
      </div>}
      {dirty && <div className="statement-actions">
        <button type="button" disabled={busy || Object.values(drafts).some((draft) => draft.merchant !== undefined && !draft.merchant.trim())}
          onClick={saveCorrections}>Save corrections</button>
        <button type="button" disabled={busy} onClick={() => setDrafts({})}>Discard corrections</button>
        <span className="statement-muted">Save or discard edits before continuing.</span>
      </div>}
      {!approvalCount && <p className="statement-muted">Approve at least one row to continue.</p>}
      <div className="statement-actions">
        <button type="button" disabled={busy || dirty} onClick={onBack}>Back to upload</button>
        <button type="button" className="statement-primary" disabled={busy || dirty || !approvalCount} onClick={onNext}>Review import totals</button>
      </div>
    </section>
  );
}

StatementReview.propTypes = {
  rows: PropTypes.arrayOf(PropTypes.object).isRequired,
  busy: PropTypes.bool.isRequired,
  onReview: PropTypes.func.isRequired,
  onNext: PropTypes.func.isRequired,
  onBack: PropTypes.func.isRequired,
};
