import { useEffect, useState } from "react";
import PropTypes from "prop-types";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import api from "../api";
import { displayDate, money } from "../copilotPresentation";
import { formatTimestamp, responseError } from "../virtualPortfolio";

const benchmarks = {
  "^GSPC": "S&P 500", "^IXIC": "Nasdaq Composite", "^STOXX50E": "EURO STOXX 50", "^FTSE": "FTSE 100",
};
const percentage = new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 2 });
const compact = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });
const tick = { fill: "var(--muted)", fontSize: 11 };
const tooltip = { background: "var(--surface)", borderColor: "var(--border-color)", color: "var(--ink)" };
const ratio = (value) => value == null ? "Unavailable" : percentage.format(Number(value));
const coverageStatuses = {
  available: "History received", unavailable: "History unavailable", currency_mismatch: "Currency mismatch",
  unverified_splits: "Split data could not be verified", quote_limit: "Quote limit reached",
};

function range(days) {
  const end = new Date();
  end.setUTCHours(0, 0, 0, 0);
  end.setUTCDate(end.getUTCDate() - 1);
  const start = new Date(end);
  start.setUTCDate(start.getUTCDate() - days + 1);
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
}

function AnalyticsCharts({ report }) {
  const compare = Boolean(report.benchmark);
  const rows = report.history.map((row) => ({
    ...row,
    value: row.value == null ? null : Number(row.value),
    portfolio_return: (compare ? row.aligned_portfolio_return : row.cumulative_return) == null ? null
      : Number(compare ? row.aligned_portfolio_return : row.cumulative_return),
    benchmark_return: row.benchmark_return == null ? null : Number(row.benchmark_return),
  }));
  return <div className="portfolio-charts portfolio-analytics-charts">
    <section className="portfolio-panel" aria-labelledby="historical-valuation-title">
      <h3 id="historical-valuation-title">Historical valuation</h3>
      <p className="portfolio-muted">Open simulated positions at observed closes · {report.currency}</p>
      {rows.some((row) => row.value != null) ? <div className="portfolio-plot" aria-hidden="true">
        <ResponsiveContainer width="100%" height={215} minWidth={0}>
          <LineChart data={rows} accessibilityLayer={false} margin={{ right: 14, top: 8 }}>
            <CartesianGrid vertical={false} stroke="var(--border-subtle)" />
            <XAxis dataKey="date" tick={tick} minTickGap={26} tickFormatter={(date) => date.slice(5)} />
            <YAxis tick={tick} width={50} tickFormatter={(value) => compact.format(value)} />
            <Tooltip labelFormatter={displayDate} formatter={(value) => [money(value, report.currency), "Market value"]}
              contentStyle={tooltip} itemStyle={{ color: "var(--ink)" }} />
            <Line type="linear" dataKey="value" stroke="var(--violet)" strokeWidth={2.4} connectNulls={false}
              dot={{ r: 2 }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div> : <p className="portfolio-empty">No complete historical valuation is available for this period.</p>}
    </section>
    <section className="portfolio-panel" aria-labelledby="historical-returns-title">
      <h3 id="historical-returns-title">{compare ? "Benchmark comparison" : "Cumulative portfolio return"}</h3>
      <p className="portfolio-muted">{compare
        ? report.benchmark.aligned_from
          ? `Portfolio and ${report.benchmark.label} rebased on ${displayDate(report.benchmark.aligned_from)}.`
          : "No shared valued date in the same currency. Choose another benchmark or view portfolio returns alone."
        : "Daily linked time-weighted estimate after modeled cash flows."}</p>
      {rows.some((row) => row.portfolio_return != null) ? <>
        <p className="portfolio-analytics-legend"><span>Portfolio</span>{compare && <span>{report.benchmark.label}</span>}</p>
        <div className="portfolio-plot" aria-hidden="true">
          <ResponsiveContainer width="100%" height={185} minWidth={0}>
            <LineChart data={rows} accessibilityLayer={false} margin={{ right: 14, top: 8 }}>
              <CartesianGrid vertical={false} stroke="var(--border-subtle)" />
              <XAxis dataKey="date" tick={tick} minTickGap={26} tickFormatter={(date) => date.slice(5)} />
              <YAxis tick={tick} width={56} tickFormatter={ratio} />
              <Tooltip labelFormatter={displayDate} formatter={ratio} contentStyle={tooltip} itemStyle={{ color: "var(--ink)" }} />
              <Line type="linear" name="Portfolio" dataKey="portfolio_return" stroke="var(--violet)" strokeWidth={2.3}
                connectNulls={false} dot={{ r: 2 }} isAnimationActive={false} />
              {compare && <Line type="linear" name={report.benchmark.label} dataKey="benchmark_return" stroke="var(--link-color)"
                strokeWidth={2.3} strokeDasharray="6 4" connectNulls={false} dot={{ r: 2 }} isAnimationActive={false} />}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </> : <p className="portfolio-empty">Return figures are unavailable for this selection.</p>}
    </section>
  </div>;
}
AnalyticsCharts.propTypes = { report: PropTypes.object.isRequired };

function Distribution({ report }) {
  const { allocation } = report;
  const groups = [["By company", allocation.companies], ["By sector", allocation.sectors]];
  return <section className="portfolio-panel">
    <h3>Allocation and concentration</h3>
    {allocation.concentration ? <>
      <p className="portfolio-muted">Market value on {displayDate(allocation.as_of)}. Tickers identify positions without company metadata.</p>
      <dl className="portfolio-kpis">
        <div><dt>Largest company</dt><dd>{ratio(allocation.concentration.top_company_weight)}</dd></div>
        <div><dt>Top three companies</dt><dd>{ratio(allocation.concentration.top_three_company_weight)}</dd></div>
        <div><dt>Company concentration (HHI)</dt><dd>{Number(allocation.concentration.company_hhi).toFixed(3)}</dd><dd>Scale of 0–1</dd></div>
        <div><dt>Largest known sector</dt><dd>{ratio(allocation.concentration.largest_known_sector_weight)}</dd></div>
        <div><dt>Unknown sector exposure</dt><dd>{ratio(allocation.concentration.unknown_sector_weight)}</dd></div>
      </dl>
      <div className="portfolio-analytics-distribution">{groups.map(([label, rows]) => <div key={label}>
        <h4>{label}</h4>
        <ul className="portfolio-allocation">{rows.map((row) => <li key={row.label}>
          <strong>{row.label}</strong><span>{money(row.value, report.currency)} · {ratio(row.weight)}</span>
        </li>)}</ul>
      </div>)}</div>
    </> : <p className="portfolio-empty">
      {allocation.available ? "No open positions at the latest valued close." : "Allocation requires a complete valuation at the latest observed close."}
    </p>}
  </section>;
}
Distribution.propTypes = { report: PropTypes.object.isRequired };

export default function PortfolioAnalytics({ portfolioId, revision }) {
  const [open, setOpen] = useState(false);
  const [days, setDays] = useState(30);
  const [benchmark, setBenchmark] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [response, setResponse] = useState(null);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState("");
  const [notice, setNotice] = useState("");
  const path = `/api/portfolios/${portfolioId}/analytics/`;
  const key = `${portfolioId}:${revision}:${days}:${benchmark}:${refresh}`;
  const state = response?.key === key ? response : null;

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    const params = { ...range(days), ...(benchmark && { benchmark }) };
    api.get(path, { params, signal: controller.signal }).then(({ data }) => {
      if (!controller.signal.aborted) setResponse({ key, report: data, params });
    }).catch((failure) => {
      if (!controller.signal.aborted) setResponse({ key, error: responseError(failure, "Couldn’t load advanced analytics.") });
    });
    return () => controller.abort();
  }, [benchmark, days, key, open, path]);

  async function exportReport() {
    if (exporting || !state?.report) return;
    setExporting(true);
    setExportError("");
    setNotice("");
    try {
      const { data } = await api.get(`${path}export/`, { params: state.params, responseType: "blob" });
      const url = URL.createObjectURL(data);
      const link = document.createElement("a");
      link.href = url;
      link.download = `virtual-portfolio-${state.params.start}-${state.params.end}.csv`;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice("CSV download started.");
    } catch {
      setExportError("Couldn’t download the analytics CSV. Try again.");
    } finally {
      setExporting(false);
    }
  }

  const report = state?.report;
  return <details className="portfolio-panel portfolio-advanced" onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary>Advanced portfolio analytics</summary>
    {open && <>
      <div className="portfolio-create">
        <label>Period<select value={days} onChange={(event) => setDays(Number(event.target.value))}>
          <option value={30}>30 days</option><option value={90}>90 days</option><option value={365}>1 year</option>
        </select></label>
        <label>Market benchmark<select value={benchmark} onChange={(event) => setBenchmark(event.target.value)}>
          <option value="">Portfolio only</option>
          {Object.entries(benchmarks).map(([symbol, label]) => <option key={symbol} value={symbol}>{label}</option>)}
        </select></label>
        <button type="button" disabled={!report || exporting} onClick={exportReport}>{exporting ? "Exporting…" : "Export analytics CSV"}</button>
      </div>
      <p role="status" className="portfolio-status">{notice}</p>
      {exportError && <p role="alert" className="portfolio-alert">{exportError}</p>}
      {!state && <p role="status">Loading historical valuations…</p>}
      {state?.error && <p role="alert" className="portfolio-alert">{state.error} <button type="button" onClick={() => setRefresh((value) => value + 1)}>Try again</button></p>}
      {report && <>
        <p className="portfolio-muted">Observed sessions through {displayDate(report.end)} · Simulated, price-only returns</p>
        {report.missing_valuation_days > 0 && <p className="portfolio-alert">
          {report.missing_valuation_days} observed dates have incomplete prices or share data. Missing valuations appear as gaps and break the cumulative return chain.
        </p>}
        {report.missing_valuation_days === 0 && Object.values(report.coverage).some((item) => item.status !== "available") &&
          <p className="portfolio-alert">Some market histories were unavailable for this selection. See coverage details below.</p>}
        <AnalyticsCharts report={report} />
        <Distribution report={report} />
        <details className="portfolio-panel"><summary>Historical values, cash flows, and returns</summary>
          {report.history.length ? <div className="portfolio-table-scroll" tabIndex={0} role="region" aria-label="Historical values and returns">
            <table className="portfolio-holdings"><thead><tr>
              <th>Date</th><th>Market value</th><th>Contributions</th><th>Withdrawals</th>
              <th>Daily return</th><th>Cumulative return</th>{report.benchmark && <th>Benchmark return</th>}
            </tr></thead><tbody>{report.history.map((row) => <tr key={row.date}>
              <th scope="row">{displayDate(row.date)}{Object.keys(row.missing_prices).length > 0 &&
                <small>Missing {Object.keys(row.missing_prices).join(", ")}</small>}</th>
              <td>{row.value == null ? "Unavailable" : money(row.value, report.currency)}</td>
              <td>{money(row.contributions, report.currency)}</td><td>{money(row.withdrawals, report.currency)}</td>
              <td>{ratio(row.daily_return)}</td><td>{ratio(row.cumulative_return)}</td>
              {report.benchmark && <td>{ratio(row.benchmark_return)}</td>}
            </tr>)}</tbody></table>
          </div> : <p>No recorded sessions in this range.</p>}
        </details>
        <details className="portfolio-panel"><summary>Market-data coverage and methodology</summary>
          <ul className="portfolio-coverage">{Object.entries(report.coverage).map(([ticker, item]) => <li key={ticker}>
            <strong>{ticker}</strong> · {coverageStatuses[item.status] ?? item.status}
            {item.last_close && ` · Last close ${displayDate(item.last_close)}`}
            {item.retrieved_at && ` · Retrieved ${formatTimestamp(item.retrieved_at)}`}
          </li>)}</ul>
          <ul>{report.notices.map((text) => <li key={text}>{text}</li>)}</ul>
        </details>
      </>}
    </>}
  </details>;
}
PortfolioAnalytics.propTypes = { portfolioId: PropTypes.number.isRequired, revision: PropTypes.number.isRequired };
