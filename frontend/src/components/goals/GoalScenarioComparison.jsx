import PropTypes from "prop-types";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { displayDate, money } from "../../copilotPresentation";

const month = new Intl.DateTimeFormat(undefined, { month: "short", year: "numeric", timeZone: "UTC" });

function completionText(plan, hypothetical) {
  if (plan.status === "completed") return hypothetical ? `Funded immediately · ${displayDate(plan.as_of)}` : "Already funded";
  if (plan.status === "no_contribution_rate") return "No completion estimate";
  return displayDate(plan.projected_completion_date) || "Outside calendar range";
}

export default function GoalScenarioComparison({ result }) {
  const { baseline, scenario, currency, months_saved: months, chart, assumptions } = result;
  const rows = chart.points.map((point) => ({ ...point, baseline: Number(point.baseline), scenario: Number(point.scenario) }));
  const plans = [{ label: "Baseline", data: baseline }, { label: "Hypothetical scenario", data: scenario }];
  return <>
    <section className="goals-card" aria-label="Estimated completion comparison">
      <h2>Estimated completion</h2>
      <div className="goals-scenario-plans">
        {plans.map(({ label, data }, index) => <div key={label}>
          <h3>{label}</h3>
          <p className="goals-scenario-date">{completionText(data, index === 1)}</p>
          <dl>
            <div><dt>Starting savings</dt><dd>{money(data.starting_amount, currency)}</dd></div>
            <div><dt>Monthly savings</dt><dd>{money(data.monthly_contribution, currency)}</dd></div>
            <div><dt>Target amount</dt><dd>{money(data.target_amount, currency)}</dd></div>
            <div><dt>Target date</dt><dd>{displayDate(data.target_date) || "No date set"}</dd></div>
          </dl>
          {data.status === "estimated" && data.projected_on_time !== null && <p className="goals-muted">
            {data.projected_on_time ? "Estimated to meet the target date." : "Estimated to finish after the target date."}
          </p>}
        </div>)}
      </div>
      {months !== null && <p className="goals-scenario-result" role="status">
        {months === 0 ? "Same time to reach the target." :
          `Estimated ${Math.abs(months)} ${Math.abs(months) === 1 ? "month" : "months"} ${months > 0 ? "sooner" : "later"} than baseline.`}
      </p>}
    </section>
    <section className="goals-card" aria-label="Projected goal progress">
      <h2>Projected goal progress</h2>
      <p className="goals-muted">Percentage funded for each plan’s target. {chart.truncated && "The chart shows the first five years."}</p>
      <div className="goals-scenario-legend"><span>Baseline</span><span>Hypothetical scenario</span></div>
      <div aria-hidden="true" className="goals-scenario-chart">
        <ResponsiveContainer width="100%" height={230} minWidth={0}>
          <LineChart data={rows} accessibilityLayer={false} margin={{ left: 0, right: 12, top: 5, bottom: 4 }}>
            <CartesianGrid vertical={false} stroke="var(--border-subtle)" />
            <XAxis dataKey="date" minTickGap={28} tick={{ fill: "var(--muted)", fontSize: 11 }}
              tickFormatter={(date) => month.format(new Date(`${date}T00:00:00Z`))} />
            <YAxis domain={[0, 100]} width={45} tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={(value) => `${value}%`} />
            <Tooltip labelFormatter={displayDate} formatter={(value) => `${value}%`}
              contentStyle={{ background: "var(--surface)", color: "var(--ink)", borderColor: "var(--border-color)" }} />
            <Line dataKey="baseline" name="Baseline" type="stepAfter" stroke="var(--muted)" strokeWidth={2}
              activeDot={false} dot={false} isAnimationActive={false} />
            <Line dataKey="scenario" name="Hypothetical scenario" type="stepAfter" stroke="var(--violet)" strokeWidth={2.5}
              strokeDasharray="6 4" dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <details>
        <summary>View monthly progress data</summary>
        <div className="goals-scenario-table">
          <table>
            <thead><tr><th scope="col">Date</th><th scope="col">Baseline</th><th scope="col">Scenario</th></tr></thead>
            <tbody>{chart.points.map((point) => <tr key={point.date}>
              <th scope="row">{displayDate(point.date)}</th><td>{point.baseline}%</td><td>{point.scenario}%</td>
            </tr>)}</tbody>
          </table>
        </div>
      </details>
    </section>
    <section className="goals-card" aria-label="Projection assumptions">
      <h2>Assumptions and uncertainty</h2>
      <ul className="goals-scenario-assumptions">
        {assumptions.map((item) => <li key={item}>{item}</li>)}
      </ul>
    </section>
  </>;
}

const plan = PropTypes.shape({
  status: PropTypes.string.isRequired, as_of: PropTypes.string.isRequired, projected_completion_date: PropTypes.string,
  projected_on_time: PropTypes.bool, target_date: PropTypes.string, target_amount: PropTypes.string.isRequired,
  starting_amount: PropTypes.string.isRequired, monthly_contribution: PropTypes.string.isRequired,
});
GoalScenarioComparison.propTypes = {
  result: PropTypes.shape({
    baseline: plan.isRequired, scenario: plan.isRequired, currency: PropTypes.string.isRequired, months_saved: PropTypes.number,
    chart: PropTypes.shape({
      points: PropTypes.arrayOf(PropTypes.shape({ date: PropTypes.string, baseline: PropTypes.string, scenario: PropTypes.string })).isRequired,
      truncated: PropTypes.bool.isRequired,
    }).isRequired,
    assumptions: PropTypes.arrayOf(PropTypes.string).isRequired,
  }).isRequired,
};
