import { isPossibleDuplicate } from "./statementReview.js";

export const importSteps = ["Upload", "Parse", "Review", "Confirm", "Complete"];

export function validateStatementFiles(files) {
  if (files.length !== 1) return "Choose exactly one statement file.";
  const [file] = files;
  if (!/\.(pdf|csv)$/i.test(file.name)) return "Unsupported format. Choose a PDF or CSV statement.";
  if (!file.size) return "The statement is empty. Choose a file with transactions.";
  if (file.size > 10 * 1024 * 1024) return "Choose a statement no larger than 10 MB.";
  return "";
}

export function importSummary(rows) {
  const selected = rows.filter(({ decision }) => decision === "approved").length;
  const duplicates = rows.filter(isPossibleDuplicate).length;
  return { total: rows.length, selected, duplicates, skipped: rows.length - selected };
}
