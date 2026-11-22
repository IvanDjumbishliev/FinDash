import { useEffect, useState } from "react";
import PropTypes from "prop-types";
import { Link } from "react-router-dom";
import { FiArrowUpRight, FiBarChart2, FiCalendar, FiCreditCard, FiPieChart, FiShoppingBag, FiTarget, FiTrendingUp, FiZap } from "react-icons/fi";
import api from "../api";
import { displayDate, money } from "../copilotPresentation";
import { categoryLabel, monthLabel } from "../budgets";

export function DashboardCard({ title, icon: Icon, route, link, children, wide }) {
  return <section className={`dash-panel${wide ? " dash-wide" : ""}`} aria-label={title}>
    <header className="dash-panel-header">
      <span className="dash-icon"><Icon aria-hidden="true" /></span>
      <h2>{title}</h2>
      {route && <Link className="dash-link" to={route}>{link} <FiArrowUpRight aria-hidden="true" /></Link>}
    </header>
    {children}
  </section>;
}

export function DashboardLoading({ label = "Loading dashboard" }) {
  return <div className="dash-loading" role="status" aria-label={label}>
    <span /><span /><span />
  </div>;
}

function Empty({ children }) {
  return <p className="dash-empty">{children}</p>;
}

export function DashboardError({ children, onRetry }) {
  return <div className="dash-error">
    <p role="alert">{children}</p><button className="dash-button" onClick={onRetry}>Retry</button>
  </div>;
}

function Rows({ rows }) {
  return <ul className="dash-rows">{rows.map(({ id, title, subtitle, value }) => <li key={id}>
    <span><strong>{title}</strong>{subtitle && <small>{subtitle}</small>}</span>
    <strong>{value}</strong>
  </li>)}</ul>;
}

const retailerNames = { lidl: "Lidl", kaufland: "Kaufland", fantastico: "Фантастико" };
const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });

export function DashboardDataCard({ type, data }) {
  const activity = data.activity || [];
  switch (type) {
    case "monthly":
      return <DashboardCard title="Monthly cash flow" icon={FiTrendingUp} route="/reports" link="Reports" wide>
        <p className="dash-note">Month to date · {monthLabel(data.month)}</p>
        {activity.length ? <div className="dash-monthly">{activity.map((row) => <dl key={row.currency}>
          <div><dt>Income</dt><dd>{money(row.income, row.currency)}</dd></div>
          <div><dt>Expenses after refunds</dt><dd>{money(row.expenses, row.currency)}</dd></div>
          <div><dt>Net cash flow</dt><dd>{money(row.net, row.currency)}</dd></div>
        </dl>)}</div> : <Empty>Record a transaction or import a statement to see this month’s cash flow.</Empty>}
      </DashboardCard>;
    case "overview":
      return <DashboardCard title="Financial overview" icon={FiCreditCard} route="/transactions" link="Transactions" wide>
        <div className="dash-overview">
          <div><h3>Spending by category</h3>
            {activity.some(({ categories }) => Object.values(categories).some((amount) => Number(amount) > 0))
              ? activity.map((row) => {
                const sorted = Object.entries(row.categories).filter(([, amount]) => Number(amount) > 0)
                  .sort((a, b) => Number(b[1]) - Number(a[1]));
                if (!sorted.length) return null;
                return <ul className="dash-bars" key={row.currency} aria-label={`Recorded ${row.currency} expenses`}>
                  {sorted.map(([category, amount]) => <li key={category}>
                    <span>{categoryLabel(category)}</span><strong>{money(amount, row.currency)}</strong>
                    <span className="dash-bar" aria-hidden="true"><i style={{ width: `${Number(amount) / Number(sorted[0][1]) * 100}%` }}/></span>
                  </li>)}
                </ul>;
              }) : <Empty>No net expenses recorded this month.</Empty>}
          </div>
          <div><h3>Recent activity</h3>
            {data.recent.length ? <Rows rows={data.recent.map((row) => ({
              id: row.id, title: row.particulars || categoryLabel(row.category),
              subtitle: dateTime.format(new Date(row.timestamp)), value: money(row.amount, row.currency),
            }))} /> : <Empty>No recent transactions.</Empty>}
          </div>
        </div>
      </DashboardCard>;
    case "budgets":
      return <DashboardCard title="Budget progress" icon={FiBarChart2} route="/budgets" link="Budgets">
        {data.budgets.length ? <ul className="dash-bars">{data.budgets.slice(0, 5).map((row) => <li key={row.id}>
          <span>{categoryLabel(row.category)} · {row.currency}</span><strong>{Math.round(Number(row.percentage_used))}% used</strong>
          <span className="dash-bar" aria-hidden="true"><i style={{ width: `${Math.min(100, Math.max(0, Number(row.percentage_used)))}%` }} /></span>
        </li>)}</ul> : <Empty>Set a monthly budget to track spending against a limit.</Empty>}
      </DashboardCard>;
    case "subscriptions":
      return <DashboardCard title="Upcoming subscriptions" icon={FiCalendar} route="/subscriptions" link="Subscriptions">
        {data.subscriptions.length ? <Rows rows={data.subscriptions.map((row) => ({
          id: row.id, title: row.merchant, subtitle: `Expected ${displayDate(row.date)}`, value: money(row.amount, row.currency),
        }))} /> : <Empty>No confirmed subscriptions due in the next 31 days.</Empty>}
      </DashboardCard>;
    case "goals":
      return <DashboardCard title="Financial goals" icon={FiTarget} route="/goals" link="Goals">
        {data.goals.length ? <Rows rows={data.goals.map((row) => ({
          id: row.currency, title: `${row.count} ${row.count === 1 ? "goal" : "goals"} · ${row.currency}`,
          subtitle: `Target ${money(row.target, row.currency)}`, value: money(row.saved, row.currency),
        }))} /> : <Empty>Create a savings goal to track contributions.</Empty>}
      </DashboardCard>;
    case "insights":
      return <DashboardCard title="Financial insights" icon={FiZap} route="/chat" link="AI advisor">
        {data.insight ? <><p className="dash-note">Last saved Copilot answer</p><p className="dash-insight-answer">{data.insight}</p></>
          : activity.length ? <ul className="dash-insights">{activity.map((row) => <li key={row.currency}>
            <strong>{row.currency} · {monthLabel(data.month)}</strong>
            <p>Recorded income was {money(row.income, row.currency)} and expenses after refunds were {money(row.expenses, row.currency)}.</p>
          </li>)}</ul> : <Empty>Record activity to see spending insights, or open the AI advisor to ask a question.</Empty>}
      </DashboardCard>;
    case "portfolio":
      return <DashboardCard title="Virtual portfolio" icon={FiPieChart} route="/portfolios" link="Simulator">
        <p className="dash-note">{data.portfolio.count} simulated {data.portfolio.count === 1 ? "portfolio" : "portfolios"}</p>
        {data.portfolio.trades.length ? <Rows rows={data.portfolio.trades.map((row) => ({
          id: row.id, title: row.ticker, subtitle: `Simulated ${row.side} · ${Number(row.quantity)} units`,
          value: `${money(row.price, row.currency)} per unit`,
        }))} /> : <Empty>No simulated trades recorded.</Empty>}
      </DashboardCard>;
    case "deals":
      return <DashboardCard title="Shopping deal highlights" icon={FiShoppingBag} route="/promotions" link="All deals">
        {data.deals.length ? <Rows rows={data.deals.map((row) => ({
          id: row.id, title: row.product_name,
          subtitle: `${retailerNames[row.retailer] || row.retailer} · ${row.expires_on ? `Ends ${displayDate(row.expires_on)}` : "Advertised offer"}`,
          value: row.display_price || money(row.price, row.currency),
        }))} /> : <Empty>No current catalog offers. Browse the retailer deals page for advertised promotions.</Empty>}
      </DashboardCard>;
    default:
      return null;
  }
}

const separate = {
  forecast: { title: "Cash flow forecast", icon: FiTrendingUp, route: "/forecast", link: "Forecast", url: "/api/forecast/cash-flow/?summary_only=true" },
};

export function DashboardLiveCard({ type, revision }) {
  const { title, icon, route, link, url } = separate[type];
  const [result, setResult] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const version = `${revision}:${attempt}`;
  useEffect(() => {
    const controller = new AbortController();
    api.get(url, { timeout: 12_000, signal: controller.signal }).then(({ data }) => {
      if (!controller.signal.aborted) setResult({ version, data });
    }).catch(() => {
      if (!controller.signal.aborted) setResult({ version, failed: true });
    });
    return () => controller.abort();
  }, [url, version]);

  const current = result?.version === version ? result : null;
  return <DashboardCard title={title} icon={icon} route={route} link={link}>
    {!current ? <DashboardLoading label={`Loading ${title.toLowerCase()}`} /> : current.failed
      ? <DashboardError onRetry={() => setAttempt((value) => value + 1)}>Could not load this widget.</DashboardError>
      : <div className="dash-forecast">
        <p className="dash-note">Next 30 days · {current.data.status === "estimated" ? "Estimated net cash flow" : "Scheduled cash flow only"}</p>
        <strong>{money(current.data.totals.estimated_net_cash_flow ?? current.data.totals.scheduled_net_cash_flow, current.data.currency)}</strong>
        {current.data.status !== "estimated" && <p className="dash-note">More history is needed for a variable-income and spending estimate.</p>}
      </div>}
  </DashboardCard>;
}

DashboardCard.propTypes = {
  title: PropTypes.string.isRequired, icon: PropTypes.elementType.isRequired, route: PropTypes.string,
  link: PropTypes.string, children: PropTypes.node.isRequired, wide: PropTypes.bool,
};
DashboardLoading.propTypes = { label: PropTypes.string };
Empty.propTypes = { children: PropTypes.node.isRequired };
DashboardError.propTypes = { children: PropTypes.node.isRequired, onRetry: PropTypes.func.isRequired };
Rows.propTypes = { rows: PropTypes.arrayOf(PropTypes.object).isRequired };
DashboardDataCard.propTypes = { type: PropTypes.string.isRequired, data: PropTypes.object.isRequired };
DashboardLiveCard.propTypes = { type: PropTypes.oneOf(["forecast"]).isRequired, revision: PropTypes.number.isRequired };
