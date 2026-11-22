import { Link } from "react-router-dom";
import PropTypes from "prop-types";
import { FiArrowUpRight } from "react-icons/fi";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

const prices = new Intl.NumberFormat(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 });
const volumes = new Intl.NumberFormat();
const dates = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

function range(low, high) {
  return low != null && high != null && low <= high ? `${prices.format(low)} – ${prices.format(high)}` : "Unavailable";
}

export default function StockMarketCard({ stock, loading }) {
  const { symbol, name, market = {}, history = [], error } = stock;
  const first = history[0];
  const last = history.at(-1);
  const change = history.length > 1 ? ((last.price - first.price) / first.price) * 100 : null;
  const price = market.price ?? last?.price;
  const asOf = market.quoted_at ? dates.format(new Date(market.quoted_at)) : null;
  return (
    <article className="stock-chart" aria-label={`${name} (${symbol})`}>
      <header className="stock-company">
        <div>
          <p className="stock-symbol">{symbol}{market.exchange && ` · ${market.exchange}`}</p>
          <h2>{name}</h2>
        </div>
        <Link className="stock-simulator-link" to={`/portfolios?ticker=${encodeURIComponent(symbol)}`}>
          Simulate trade <FiArrowUpRight aria-hidden="true" />
        </Link>
      </header>
      <div className="stock-quote">
        <div>
          <span className="stock-quote-value">{price != null ? prices.format(price) : "Price unavailable"} {price != null && market.currency}</span>
          {price != null && <small>{market.price != null && asOf
            ? `Last reported ${asOf}` : `Last chart value · ${last.date}`}</small>}
        </div>
        {change != null && <div className="stock-period">
          <strong>{change > 0 ? "+" : ""}{change.toFixed(2)}%</strong>
          <small>Chart period change</small>
        </div>}
      </div>
      {([market.day_low, market.day_high, market.year_low, market.year_high, market.volume].some((value) => value != null)) && (
        <dl className="stock-metrics">
          <div><dt>Session range</dt><dd>{range(market.day_low, market.day_high)}</dd></div>
          <div><dt>52-week range</dt><dd>{range(market.year_low, market.year_high)}</dd></div>
          <div><dt>Session volume</dt><dd>{market.volume != null ? volumes.format(market.volume) : "Unavailable"}</dd></div>
        </dl>
      )}
      {history.length ? (
        <div className="stock-price-history">
          <p>Daily prices · {first.date} to {last.date}</p>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={history} title={`${symbol} daily price history`}>
              <CartesianGrid stroke="var(--border-subtle)" strokeDasharray="3 3" />
              <XAxis dataKey="date" minTickGap={22} tick={{ fill: "var(--muted)", fontSize: 12 }} tickFormatter={(date) => date.slice(5)} />
              <YAxis domain={["auto", "auto"]} tick={{ fill: "var(--muted)", fontSize: 12 }} width={58} tickFormatter={(value) => prices.format(value)} />
              <Tooltip
                contentStyle={{ background: "var(--surface)", borderColor: "var(--border-color)" }}
                labelStyle={{ color: "var(--ink)" }}
                itemStyle={{ color: "var(--ink)" }}
                formatter={(value) => [`${prices.format(value)}${market.currency ? ` ${market.currency}` : ""}`, "Daily price"]}
              />
              <Line type="linear" dataKey="price" stroke="var(--violet)" strokeWidth={2} dot={history.length === 1} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : <p className="stock-status" role="status">{error || (loading ? "Loading price history…" : "No price history available.")}</p>}
    </article>
  );
}

StockMarketCard.propTypes = {
  stock: PropTypes.shape({
    symbol: PropTypes.string.isRequired,
    name: PropTypes.string.isRequired,
    market: PropTypes.object,
    history: PropTypes.arrayOf(PropTypes.shape({ date: PropTypes.string.isRequired, price: PropTypes.number.isRequired })),
    error: PropTypes.string,
  }).isRequired,
  loading: PropTypes.bool.isRequired,
};
