import PropTypes from "prop-types";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { categoryLabel, spendingHistory } from "../budgets";
import { formatMoney } from "../subscriptions";

export default function BudgetSpendingChart({ periods, month, budget }) {
  if (!budget) return null;
  const series = spendingHistory(periods, month, budget);
  const format = (value) => formatMoney(value, budget.currency);

  return (
    <section className="budget-panel budget-spending" aria-labelledby="budget-spending-title">
      <h2 id="budget-spending-title">{categoryLabel(budget.category)} spending</h2>
      <p className="budget-muted">Allocated and spent in {budget.currency} across up to 12 saved months.</p>
      {series.length > 0 ? <>
        <div className="budget-legend"><span>Allocated</span><span>Spent</span></div>
        <div className="budget-chart">
          <ResponsiveContainer width="100%" height={238}>
            <BarChart data={series} margin={{ top: 6, right: 8 }}>
              <CartesianGrid vertical={false} stroke="var(--border-subtle)" />
              <XAxis dataKey="period" tickFormatter={(value) => value.slice(0, 7)}
                tick={{ fill: "var(--muted)", fontSize: 11 }} minTickGap={26} />
              <YAxis tick={{ fill: "var(--muted)", fontSize: 11 }} width={62} />
              <Tooltip
                labelFormatter={(value) => series.find((point) => point.period === value)?.month}
                formatter={(value) => format(value)}
                contentStyle={{ background: "var(--surface)", borderColor: "var(--border-color)" }}
                labelStyle={{ color: "var(--ink)" }} />
              <Bar dataKey="allocated" name="Allocated" fill="var(--violet)" radius={[4, 4, 0, 0]} />
              <Bar dataKey="spent" name="Spent" fill="var(--budget-chart-spent)" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <details>
          <summary>View chart amounts</summary>
          <ul className="budget-chart-data">
            {series.map(({ period, month, allocated, spent }) => (
              <li key={period}><strong>{month}</strong><span>{format(spent)} spent of {format(allocated)}</span></li>
            ))}
          </ul>
        </details>
      </> : <p>No budget activity to chart yet.</p>}
    </section>
  );
}

BudgetSpendingChart.propTypes = {
  periods: PropTypes.arrayOf(PropTypes.object).isRequired,
  month: PropTypes.string.isRequired,
  budget: PropTypes.shape({ category: PropTypes.string, currency: PropTypes.string }),
};
