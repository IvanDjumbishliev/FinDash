import { useState } from "react";
import PropTypes from "prop-types";
import { FiArrowDownCircle, FiArrowUpCircle, FiDownload, FiFileText, FiRefreshCw } from "react-icons/fi";
import api from "../api";
import { displayRange, money } from "../copilotPresentation";
import "../styles/pages/Reports.css";

const endpoint = "/api/reports/";
const aiMessages = {
  unavailable: "Gemini commentary is unavailable. The report and PDF export are ready.",
  not_configured: "AI commentary is unavailable on this server.",
  insufficient_data: "There is not enough recorded activity for AI commentary.",
  sharing_disabled: "AI data sharing is turned off in your Copilot privacy settings.",
};

function monthNow() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

async function errorMessage(failure, fallback) {
  let body = failure.response?.data;
  if (body instanceof Blob) {
    try {
      body = JSON.parse(await body.text());
    } catch {
      return fallback;
    }
  }
  return body?.error || body?.month?.[0] || body?.currency?.[0] || fallback;
}

function ReportTable({ title, subtitle, headers, rows, empty }) {
  return <section className="report-panel">
    <h3>{title}</h3>
    {subtitle && <p className="reports-muted">{subtitle}</p>}
    {rows.length ? <div className="report-table-scroll" tabIndex={0} role="region" aria-label={title}>
      <table>
        <thead><tr>{headers.map((label) => <th key={label} scope="col">{label}</th>)}</tr></thead>
        <tbody>{rows.map((row, index) => <tr key={index}>
          <th scope="row">{row[0]}</th>
          {row.slice(1).map((value, column) => <td key={column}>{value}</td>)}
        </tr>)}</tbody>
      </table>
    </div> : <p className="reports-muted">{empty}</p>}
  </section>;
}

ReportTable.propTypes = {
  title: PropTypes.string.isRequired,
  subtitle: PropTypes.string,
  headers: PropTypes.arrayOf(PropTypes.string).isRequired,
  rows: PropTypes.arrayOf(PropTypes.array).isRequired,
  empty: PropTypes.string.isRequired,
};

function ReportPreview({ report }) {
  const { currency, period, timezone, generated_at: generatedAt, activity, comparison, subscriptions, ai } = report;
  const amount = (value) => value === null ? "Unavailable" : money(value, currency);
  const previousRange = displayRange(comparison.period.start_date, comparison.period.end_date);
  const generated = new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium", timeStyle: "short", timeZone: timezone,
  }).format(new Date(generatedAt));

  return <div className="report-preview">
    <header className="report-preview-heading">
      <div>
        <h2>{displayRange(period.start_date, period.end_date)}</h2>
        <p>{period.partial ? "Month to date · " : ""}{currency} · {timezone}</p>
      </div>
      <time dateTime={generatedAt}>Generated {generated}</time>
    </header>
    {!activity.transaction_count && <p className="report-note">
      No transactions qualified for this period and currency. Your budgets and confirmed subscriptions can still appear below.
    </p>}
    <dl className="report-kpis">
      <div><dt><FiArrowDownCircle aria-hidden="true" /> Income</dt><dd>{amount(activity.income)}</dd></div>
      <div><dt><FiArrowUpCircle aria-hidden="true" /> Net expenses</dt><dd>{amount(activity.net_expenses)}</dd>
        <dd>Gross {amount(activity.gross_expenses)} · Refunds {amount(activity.refunds)}</dd></div>
      <div><dt>Net cash flow</dt><dd>{amount(activity.net_cash_flow)}</dd></div>
      <div><dt>Change in net expenses</dt><dd>{amount(comparison.change)}</dd>
        <dd>{comparison.change === null ? "Requires activity in both periods" : `Compared with ${previousRange}`}</dd></div>
    </dl>

    {(ai.text || aiMessages[ai.status]) && <section className="report-panel report-ai">
      <h3>AI trend interpretation</h3>
      <p>{ai.text || aiMessages[ai.status]}</p>
      {ai.notice && <p className="reports-muted">{ai.notice}</p>}
    </section>}

    <ReportTable title="Category breakdown" subtitle={`Previous period · ${previousRange}`}
      headers={["Category", "Net expenses", "Previous net expenses", "Change"]}
      rows={report.categories.map((row) => [
        row.category, amount(row.net_expenses), amount(row.previous_net_expenses), amount(row.change),
      ])} empty="No category spending recorded." />
    <ReportTable title="Largest expenses" headers={["Expense", "Date", "Category", "Amount"]}
      rows={report.largest_expenses.map((row) => [row.label, row.date, row.category, amount(row.amount)])}
      empty="No expenses recorded." />
    <ReportTable title="Budget performance" headers={["Budget", "Limit", "Actual", "Remaining", "Used"]}
      rows={report.budgets.map((row) => [row.category || "Overall", amount(row.amount), amount(row.actual_spending),
        amount(row.remaining), `${row.percentage_used}%`])} empty="No active budgets for this month and currency." />

    <section className="report-panel">
      <h3>Subscription summary</h3>
      <p className="reports-muted">Active confirmed subscriptions as of {subscriptions.as_of}. Costs are estimates.</p>
      {subscriptions.totals ? <>
        <dl className="report-subscription-totals">
          <div><dt>Subscriptions</dt><dd>{subscriptions.totals.subscription_count}</dd></div>
          <div><dt>Estimated monthly</dt><dd>{amount(subscriptions.totals.estimated_monthly)}</dd></div>
          <div><dt>Estimated annual</dt><dd>{amount(subscriptions.totals.estimated_annual)}</dd></div>
        </dl>
        {subscriptions.largest_recurring_expenses.length > 0 && <ul className="report-recurring">
          {subscriptions.largest_recurring_expenses.map((row, index) =>
            <li key={index}><span>{row.merchant}</span><span>{amount(row.amount)} · {row.frequency}</span></li>)}
        </ul>}
      </> : <p>No active confirmed subscriptions in this currency.</p>}
    </section>
    <section className="report-panel"><h3>Financial goals</h3><p>{report.goals.message}</p></section>
  </div>;
}

ReportPreview.propTypes = { report: PropTypes.object.isRequired };

export default function Reports() {
  const [month, setMonth] = useState(monthNow);
  const [currency, setCurrency] = useState("");
  const [consent, setConsent] = useState(false);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function generate(event) {
    event.preventDefault();
    if (busy) return;
    setBusy("report");
    setError("");
    setMessage("");
    setPreview(null);
    setConsent(false);
    try {
      const { data } = await api.post(endpoint, {
        month, ...(currency ? { currency } : {}), ai_consent: consent,
      });
      setPreview(data);
      setMessage("Report preview ready.");
    } catch (failure) {
      setError(await errorMessage(failure, "Couldn’t generate the report. Try again."));
    } finally {
      setBusy("");
    }
  }

  async function exportPDF() {
    if (busy || !preview) return;
    setBusy("pdf");
    setError("");
    setMessage("");
    try {
      const { data } = await api.post(`${endpoint}pdf/`, preview, { responseType: "blob" });
      const url = URL.createObjectURL(data);
      const link = document.createElement("a");
      link.href = url;
      link.download = `findash-report-${preview.report.period.month}-${preview.report.currency}.pdf`;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setMessage("PDF download started.");
    } catch (failure) {
      setError(await errorMessage(failure, "Couldn’t export the PDF. Try generating a fresh report."));
    } finally {
      setBusy("");
    }
  }

  return <main className="reports-page">
    <header className="reports-heading">
      <span className="reports-mark"><FiFileText aria-hidden="true" /></span>
      <div><h1>Financial reports</h1><p>Review your recorded activity for a month and download a PDF.</p></div>
    </header>
    <form className="report-panel reports-form" onSubmit={generate}>
      <div className="reports-fields">
        <label>Report month<input type="month" value={month} required disabled={Boolean(busy)}
          onChange={(event) => setMonth(event.target.value)} /></label>
        <label>Currency<input type="text" value={currency} placeholder="Account default" maxLength={3}
          pattern="[A-Z]{3}" disabled={Boolean(busy)}
          onChange={(event) => setCurrency(event.target.value.toUpperCase())} /></label>
        <button className="reports-primary" type="submit" disabled={Boolean(busy)}>
          <FiRefreshCw aria-hidden="true" /> {busy === "report" ? "Generating…" : "Generate report"}
        </button>
      </div>
      <label className="reports-consent">
        <input type="checkbox" checked={consent} disabled={Boolean(busy)} onChange={(event) => setConsent(event.target.checked)} />
        Allow Gemini to interpret broad trends for this report
      </label>
      <p className="reports-muted">Optional. Only trend directions and category names are shared.</p>
    </form>

    {error && <p className="report-note report-error" role="alert">{error}</p>}
    <p className="reports-status" role="status">{busy === "report" ? "Preparing the monthly report…" : message}</p>
    {preview ? <>
      <div className="reports-actions">
        <button type="button" className="reports-primary" onClick={exportPDF} disabled={Boolean(busy)}>
          <FiDownload aria-hidden="true" /> {busy === "pdf" ? "Exporting…" : "Export PDF"}
        </button>
        <button type="button" onClick={() => {
          setPreview(null);
          setError("");
          setMessage("Preview cleared.");
        }} disabled={Boolean(busy)}>Clear preview</button>
      </div>
      <ReportPreview report={preview.report} />
    </> : !busy && !error && <section className="report-panel report-empty">
      <FiFileText aria-hidden="true" /><h2>No report preview</h2>
      <p>Select a month and generate a report to see what was recorded.</p>
    </section>}
  </main>;
}
