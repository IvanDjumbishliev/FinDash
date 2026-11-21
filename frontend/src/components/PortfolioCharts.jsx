import PropTypes from "prop-types";
import { CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { money } from "../copilotPresentation";
import { allocation, formatTimestamp } from "../virtualPortfolio";

const colors = ["#7254df", "#268b91", "#e08248", "#6175c3", "#bb5b85", "#9a8640"];
const compact = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });
const tooltip = { background: "var(--surface)", borderColor: "var(--border-color)", color: "var(--ink)" };
const tick = { fill: "var(--muted)", fontSize: 11 };
const percent = new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 1 });

export default function PortfolioCharts({ snapshot, currency }) {
  const { label, rows } = allocation(snapshot);
  const total = rows.reduce((sum, row) => sum + row.value, 0);
  const timeline = snapshot.history.map((point, index) => ({
    ...point, index: index + 1, value: Number(point.realized_pnl),
  }));
  const format = (amount) => money(amount, currency);

  return <div className="portfolio-charts">
    <section className="portfolio-panel" aria-labelledby="portfolio-allocation-heading">
      <h2 id="portfolio-allocation-heading">Asset allocation</h2>
      <p className="portfolio-muted">{label} · {currency}{snapshot.performance.valuation_complete ? "" : " · Some market quotes are unavailable."}</p>
      {rows.length ? <>
        <div className="portfolio-plot" aria-hidden="true">
          <ResponsiveContainer width="100%" height={190} minWidth={0}>
            <PieChart accessibilityLayer={false}>
              <Pie data={rows} nameKey="ticker" dataKey="value" innerRadius={46} outerRadius={77} paddingAngle={2} isAnimationActive={false}>
                {rows.map((row, index) => <Cell key={row.ticker} fill={colors[index % colors.length]} />)}
              </Pie>
              <Tooltip formatter={(value) => format(value)} contentStyle={tooltip} itemStyle={{ color: "var(--ink)" }} />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <ul className="portfolio-allocation" aria-label={`Allocation by ${label.toLowerCase()}`}>
          {rows.map((row, index) => <li key={row.ticker}><i aria-hidden="true" style={{ backgroundColor: colors[index % colors.length] }} />
            <strong>{row.ticker}</strong><span>{format(row.value)} · {percent.format(row.value / total)}</span></li>)}
        </ul>
      </> : <p className="portfolio-empty">Open a simulated position to see allocation by asset.</p>}
    </section>
    <section className="portfolio-panel" aria-labelledby="portfolio-performance-heading">
      <h2 id="portfolio-performance-heading">Portfolio performance</h2>
      <p className="portfolio-muted">Cumulative realized P/L after each simulated trade · latest 100 trade events.</p>
      {timeline.length ? <>
        <div className="portfolio-plot" aria-hidden="true">
          <ResponsiveContainer width="100%" height={236} minWidth={0}>
            <LineChart data={timeline} accessibilityLayer={false} margin={{ top: 10, right: 14, bottom: 0 }}>
              <CartesianGrid stroke="var(--border-subtle)" strokeDasharray="3 4" vertical={false} />
              <XAxis dataKey="index" tick={tick} tickFormatter={(value) => `#${value}`} minTickGap={24} />
              <YAxis tick={tick} tickFormatter={(value) => compact.format(value)} width={49} />
              <ReferenceLine y={0} stroke="var(--muted)" />
              <Tooltip contentStyle={tooltip} itemStyle={{ color: "var(--ink)" }}
                labelFormatter={(value) => {
                  const point = timeline[Number(value) - 1];
                  return point ? `${point.ticker} · ${formatTimestamp(point.timestamp)}` : "";
                }} formatter={(value) => [format(value), "Realized P/L"]} />
              <Line type="stepAfter" dataKey="value" stroke="var(--violet)" strokeWidth={2.5}
                dot={timeline.length === 1} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <details className="portfolio-chart-data"><summary>View performance data</summary>
          <div className="portfolio-table-scroll" tabIndex={0} role="region" aria-label="Portfolio performance data">
            <table><thead><tr><th scope="col">Date</th><th scope="col">Simulated trade</th><th scope="col">Cumulative realized P/L</th></tr></thead>
              <tbody>{timeline.map((point) => <tr key={point.trade_id}>
                <th scope="row">{formatTimestamp(point.timestamp)}</th>
                <td>{point.side === "buy" ? "Buy" : "Sell"} {point.ticker}</td>
                <td>{format(point.realized_pnl)}</td>
              </tr>)}</tbody>
            </table>
          </div>
        </details>
      </> : <p className="portfolio-empty">Record a simulated trade to start the performance chart.</p>}
    </section>
  </div>;
}

PortfolioCharts.propTypes = { snapshot: PropTypes.object.isRequired, currency: PropTypes.string.isRequired };
