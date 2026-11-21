import PropTypes from "prop-types";
import { Area, Bar, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { displayDate, displayRange, money } from "../copilotPresentation";
import { trajectory, weeklyCashFlow } from "../cashFlowForecast";

const axisTick = { fill: "var(--muted)", fontSize: 11 };
const compact = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });
const tooltipStyle = { background: "var(--surface)", borderColor: "var(--border-color)", color: "var(--ink)" };
const ticks = { tick: axisTick, tickLine: false, axisLine: false };

function shortDate(value) {
  return value.slice(5);
}

function WeeklyChart({ rows, currency, projected, domain }) {
  if (!rows.length) return <p className="forecast-chart-empty">
    {projected ? "No scheduled cash flows fall in this horizon." : "No recent transactions are available to chart."}
  </p>;
  return <div className="forecast-chart-plot" aria-hidden="true">
    <ResponsiveContainer width="100%" height={210} minWidth={0}>
      <ComposedChart data={rows} accessibilityLayer={false} margin={{ top: 12, right: 12, bottom: 0, left: 2 }}>
        <CartesianGrid vertical={false} stroke="var(--border-subtle)" strokeDasharray="3 4" />
        <XAxis dataKey="end" {...ticks} tickFormatter={shortDate} minTickGap={22} />
        <YAxis {...ticks} tickFormatter={(value) => compact.format(value)} width={43} domain={domain} />
        <ReferenceLine y={0} stroke="var(--muted)" />
        <Tooltip labelFormatter={(end) => displayRange(rows.find((row) => row.end === end)?.start, end)}
          formatter={(value) => [money(value, currency), "Net cash flow"]}
          contentStyle={tooltipStyle} itemStyle={{ color: "var(--ink)" }} />
        {projected
          ? <Line type="linear" dataKey="value" stroke="var(--forecast-projected)" strokeWidth={2.5}
              strokeDasharray="6 4" dot={{ r: 3 }} isAnimationActive={false} />
          : <Bar dataKey="value" fill="var(--forecast-actual)" maxBarSize={28} isAnimationActive={false} />}
      </ComposedChart>
    </ResponsiveContainer>
  </div>;
}

const week = PropTypes.shape({ start: PropTypes.string, end: PropTypes.string, value: PropTypes.number, count: PropTypes.number });
WeeklyChart.propTypes = {
  rows: PropTypes.arrayOf(week).isRequired,
  currency: PropTypes.string.isRequired,
  projected: PropTypes.bool,
  domain: PropTypes.arrayOf(PropTypes.number).isRequired,
};

export function CashFlowComparison({ data }) {
  const { actual, projected } = weeklyCashFlow(data);
  const hasProjection = data.status === "estimated" || data.recurring.length > 0;
  const rows = [...actual, ...(hasProjection ? projected : [])];
  const domain = [
    Math.min(0, ...rows.map((row) => row.value)),
    Math.max(1, ...rows.map((row) => row.value)),
  ];
  const projectionLabel = data.status === "estimated" ? "Projected" : "Scheduled only";

  return <section className="forecast-panel" aria-labelledby="forecast-weekly-title">
    <h2 id="forecast-weekly-title">Cash flow by week</h2>
    <p className="forecast-muted">Income minus net expenses in {data.currency}. The two charts share a scale.</p>
    <div className="forecast-weekly-regions">
      <section className="forecast-chart-region forecast-chart-actual" aria-label="Recorded weekly cash flow">
        <h3><span aria-hidden="true" /> Recorded</h3>
        <p>{actual.length ? displayRange(actual[0].start, actual.at(-1).end) : "Recent history"}</p>
        <WeeklyChart rows={actual} currency={data.currency} domain={domain} />
      </section>
      <section className="forecast-chart-region forecast-chart-future" aria-label={`${projectionLabel} weekly cash flow`}>
        <h3><span aria-hidden="true" /> {projectionLabel}</h3>
        <p>{displayRange(data.start_date, data.end_date)}</p>
        <WeeklyChart rows={hasProjection ? projected : []} currency={data.currency} projected domain={domain} />
      </section>
    </div>
    {rows.length > 0 && <details className="forecast-chart-data">
      <summary>View weekly cash flow data</summary>
      <div className="forecast-table-scroll" tabIndex={0} role="region" aria-label="Weekly cash flow data">
        <table>
          <thead><tr><th scope="col">Period</th><th scope="col">Type</th><th scope="col">Net cash flow</th></tr></thead>
          <tbody>{[
            ...actual.map((row) => ({ ...row, label: row.count ? "Recorded" : "No recorded activity" })),
            ...(hasProjection ? projected.map((row) => ({ ...row, label: projectionLabel })) : []),
          ].map((row) => <tr key={row.end}>
            <th scope="row">{displayRange(row.start, row.end)}</th><td>{row.label}</td><td>{money(row.value, data.currency)}</td>
          </tr>)}</tbody>
        </table>
      </div>
    </details>}
  </section>;
}

export function ForecastTrajectory({ data }) {
  const rows = trajectory(data);
  const hasBalance = data.starting_balance != null;
  const full = data.status === "estimated";
  const band = rows.some((row) => row.band);
  const title = hasBalance
    ? full ? "Estimated balance trajectory" : "Scheduled-only balance path"
    : full ? "Projected cumulative cash flow" : "Cumulative scheduled cash flow";
  const range = data.uncertainty?.[hasBalance ? "ending_balance" : "net_cash_flow"];

  return <section className="forecast-panel forecast-path" aria-labelledby="forecast-path-title">
    <h2 id="forecast-path-title">{title}</h2>
    <p className="forecast-muted">{hasBalance
      ? `Starts from your supplied balance of ${money(data.starting_balance, data.currency)}.`
      : "Enter a starting balance to see projected balances. This chart shows the cumulative change."}</p>
    {(full || data.recurring.length > 0) ? <>
      {band && <div className="forecast-band-note">
        <span className="forecast-band-key" aria-hidden="true" />
        <span>Historical scenario range · 10th–90th percentiles. These illustrate outcomes from past patterns.</span>
      </div>}
      <div className="forecast-chart-plot" aria-hidden="true">
        <ResponsiveContainer width="100%" height={235} minWidth={0}>
          <ComposedChart data={rows} accessibilityLayer={false} margin={{ top: 8, right: 16, bottom: 0, left: 2 }}>
            <CartesianGrid vertical={false} stroke="var(--border-subtle)" strokeDasharray="3 4" />
            <XAxis dataKey="date" {...ticks} tickFormatter={shortDate} minTickGap={26} />
            <YAxis {...ticks} width={49} tickFormatter={(value) => compact.format(value)} domain={["auto", "auto"]} />
            <Tooltip contentStyle={tooltipStyle} labelFormatter={displayDate} itemStyle={{ color: "var(--ink)" }}
              formatter={(value, label) => [Array.isArray(value)
                ? value.map((entry) => money(entry, data.currency)).join(" – ") : money(value, data.currency), label]} />
            {band && <Area type="linear" dataKey="band" name="Historical scenario range"
              stroke="none" fill="var(--forecast-band)" isAnimationActive={false} />}
            <Line type="linear" dataKey="value" name={title} stroke="var(--forecast-projected)" strokeWidth={2.5}
              strokeDasharray="6 4" dot={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      {band && range && <p className="forecast-range"><strong>End of forecast range</strong> {money(range.lower, data.currency)} to {money(range.upper, data.currency)}</p>}
      <details className="forecast-chart-data">
        <summary>View daily trajectory data</summary>
        <div className="forecast-table-scroll" tabIndex={0} role="region" aria-label="Daily trajectory data">
          <table>
            <thead><tr><th scope="col">Date</th><th scope="col">{hasBalance ? "Balance" : "Cumulative change"}</th>
              {band && <th scope="col">Scenario range</th>}</tr></thead>
            <tbody>{rows.map((row) => <tr key={row.date}>
              <th scope="row">{displayDate(row.date)}</th><td>{money(row.value, data.currency)}</td>
              {band && <td>{row.band ? row.band.map((value) => money(value, data.currency)).join(" – ") : "—"}</td>}
            </tr>)}</tbody>
          </table>
        </div>
      </details>
    </> : <p className="forecast-chart-empty">No cash flow trajectory is available for this horizon.</p>}
  </section>;
}

const forecastData = PropTypes.shape({
  status: PropTypes.string.isRequired, currency: PropTypes.string.isRequired, history: PropTypes.object.isRequired,
  days: PropTypes.array.isRequired, recurring: PropTypes.array.isRequired,
  start_date: PropTypes.string.isRequired, end_date: PropTypes.string.isRequired,
  as_of: PropTypes.string.isRequired, starting_balance: PropTypes.string, uncertainty: PropTypes.object,
}).isRequired;
CashFlowComparison.propTypes = { data: forecastData };
ForecastTrajectory.propTypes = { data: forecastData };
