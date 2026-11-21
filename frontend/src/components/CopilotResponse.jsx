import { useState } from "react";
import PropTypes from "prop-types";
import { FiBarChart2, FiCalendar, FiCheck, FiCopy, FiTrendingUp } from "react-icons/fi";
import { Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { chartModel, displayRange, metricCards, money } from "../copilotPresentation";

function SpendingChart({ model }) {
  const [currencyChoice, setCurrencyChoice] = useState("");
  const { currency, rows } = model.series.find((item) => item.currency === currencyChoice) ?? model.series[0];
  const categoryChart = model.type === "category_breakdown";
  const height = categoryChart ? Math.max(152, rows.length * 30 + 30) : 192;
  const domain = [(min) => Math.min(min, 0), (max) => Math.max(max, 0)];
  const numericAxis = { type: "number", domain, tickCount: 4, stroke: "var(--muted)", fontSize: 11 };
  const categoryAxis = { type: "category", dataKey: "label", stroke: "var(--muted)", fontSize: 11 };

  return (
    <figure className="copilot-chart">
      <figcaption>
        <span><FiBarChart2 aria-hidden="true" /> {model.title}</span>
        {model.series.length > 1
          ? <label><span className="copilot-sr-only">Chart currency</span>
            <select value={currency} onChange={(event) => setCurrencyChoice(event.target.value)}>
              {model.series.map((item) => <option key={item.currency}>{item.currency}</option>)}
            </select>
          </label>
          : <span className="copilot-chart-currency">{currency}</span>}
      </figcaption>
      <div className="copilot-chart-plot" aria-hidden="true">
        <ResponsiveContainer width="100%" height={height} minWidth={0}>
          <BarChart data={rows} layout={categoryChart ? "vertical" : "horizontal"} accessibilityLayer={false}
            margin={{ top: 6, right: 18, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--border-subtle)" strokeDasharray="3 4" horizontal={!categoryChart} vertical={categoryChart} />
            {categoryChart ? <>
              <XAxis {...numericAxis} />
              <YAxis {...categoryAxis} width={95} interval={0} />
              <ReferenceLine x={0} stroke="var(--muted)" />
            </> : <>
              <XAxis {...categoryAxis} />
              <YAxis {...numericAxis} width={45} />
              <ReferenceLine y={0} stroke="var(--muted)" />
            </>}
            <Tooltip formatter={(value) => [money(value, currency), "Net spending"]}
              contentStyle={{ background: "var(--surface)", color: "var(--ink)", borderColor: "var(--border-color)" }}
              itemStyle={{ color: "var(--ink)" }} cursor={{ fill: "var(--accent-surface)" }} />
            <Bar dataKey="value" fill="var(--violet)" radius={4} maxBarSize={categoryChart ? 17 : 64} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <details className="copilot-chart-data">
        <summary>View chart data</summary>
        <table>
          <caption className="copilot-sr-only">{model.title} in {currency}</caption>
          <thead><tr><th scope="col">{categoryChart ? "Category" : "Period"}</th><th scope="col">Net spending</th></tr></thead>
          <tbody>{rows.map((row) => <tr key={row.label}>
            <th scope="row">{row.label}{row.detail && <small>{row.detail}</small>}</th>
            <td>{money(row.value, currency)}</td>
          </tr>)}</tbody>
        </table>
      </details>
    </figure>
  );
}

const chartRow = PropTypes.shape({ label: PropTypes.string, detail: PropTypes.string, value: PropTypes.number });
SpendingChart.propTypes = {
  model: PropTypes.shape({
    type: PropTypes.string, title: PropTypes.string,
    series: PropTypes.arrayOf(PropTypes.shape({ currency: PropTypes.string, rows: PropTypes.arrayOf(chartRow) })),
  }).isRequired,
};

export default function CopilotResponse({ response }) {
  const [copyState, setCopyState] = useState("");
  const [showAll, setShowAll] = useState(false);
  const cards = metricCards(response.metrics);
  const chart = chartModel(response);
  const ranges = (response.date_ranges ?? []).map((range) => displayRange(range.start_date, range.end_date)).filter(Boolean);

  async function copyAnswer() {
    try {
      await navigator.clipboard.writeText(response.answer);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
  }

  return (
    <div className="copilot-response">
      {ranges.length > 0 && <ul className="copilot-ranges" aria-label="Date ranges">
        {ranges.map((range, index) => <li key={`${range}-${index}`}><FiCalendar aria-hidden="true" /> {range}</li>)}
      </ul>}
      <p className="copilot-answer">{response.answer}</p>
      {cards.length > 0 && <section className="copilot-metrics" aria-label="Supporting metrics">
        <dl>
          {cards.slice(0, showAll ? cards.length : 6).map((card, index) => <div key={`${card.label}-${index}`}>
            <dt><FiTrendingUp aria-hidden="true" /> {card.label}</dt><dd>{card.value}</dd><dd>{card.detail}</dd>
          </div>)}
        </dl>
        {cards.length > 6 && <button type="button" className="copilot-text-button" aria-expanded={showAll}
          onClick={() => setShowAll((show) => !show)}>{showAll ? "Show fewer metrics" : `Show all ${cards.length} metrics`}</button>}
      </section>}
      {chart && <SpendingChart model={chart} />}
      <div className="copilot-response-actions">
        <button type="button" className="copilot-text-button" onClick={copyAnswer}>
          {copyState === "copied" ? <FiCheck aria-hidden="true" /> : <FiCopy aria-hidden="true" />}
          {copyState === "copied" ? "Copied" : "Copy response"}
        </button>
        <span role="status">{copyState === "failed" ? "Couldn’t copy. You can select and copy the answer manually." : copyState === "copied" ? <span className="copilot-sr-only">Response copied.</span> : null}</span>
      </div>
    </div>
  );
}

CopilotResponse.propTypes = {
  response: PropTypes.shape({
    answer: PropTypes.string.isRequired,
    metrics: PropTypes.array,
    date_ranges: PropTypes.arrayOf(PropTypes.shape({ start_date: PropTypes.string, end_date: PropTypes.string })),
    visualization: PropTypes.shape({ type: PropTypes.string, metric_index: PropTypes.number }),
  }).isRequired,
};
