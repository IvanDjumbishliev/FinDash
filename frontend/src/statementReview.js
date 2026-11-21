export function isPossibleDuplicate(row) {
  return Boolean(row.duplicate_matches.existing.length || row.duplicate_matches.file.length);
}

export function bulkReviewChanges(selected, decision, allowDuplicates) {
  if (decision === "approved" && !allowDuplicates && selected.some(isPossibleDuplicate)) return [];
  return selected.map((row) => ({
    row_id: row.row_id,
    decision,
    allow_duplicate: decision === "approved" && isPossibleDuplicate(row) && allowDuplicates === true,
  }));
}
