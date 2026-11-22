import PropTypes from "prop-types";
import { money } from "../../copilotPresentation";

function Breakdown({ rows, currency, truncated, empty }) {
  if (!rows.length) return <p className="receipt-muted">{empty}</p>;
  const scale = Math.max(0, ...rows.map(({ total }) => Math.abs(Number(total))));
  return <>
    <ul className="receipt-breakdown">
      {rows.map(({ name, total, line_count }) => <li key={name}>
        <div><strong>{name || "Uncategorized"}</strong><span>{money(total, currency)}</span></div>
        <meter min="0" max={scale || 1} value={Math.abs(Number(total))} aria-hidden="true" />
        <small>{line_count} {line_count === 1 ? "line" : "lines"}</small>
      </li>)}
    </ul>
    {truncated && <p className="receipt-muted">Showing the 25 highest totals. Narrow the filters to see more.</p>}
  </>;
}

const breakdown = PropTypes.arrayOf(PropTypes.shape({
  name: PropTypes.string.isRequired, total: PropTypes.string.isRequired, line_count: PropTypes.number.isRequired,
}));

Breakdown.propTypes = { rows: breakdown.isRequired, currency: PropTypes.string.isRequired,
  truncated: PropTypes.bool.isRequired, empty: PropTypes.string.isRequired };

export default function ReceiptStatistics({ statistics }) {
  if (!statistics.length) return <p className="receipt-muted">Spending details appear when saved receipts match these filters.</p>;
  return <>
    <p className="receipt-muted">These totals come from receipts. Linked payments stay in bank analytics, so do not add the two totals together.</p>
    {statistics.map((entry) => <section className="receipt-stat-currency" key={entry.currency} aria-label={`${entry.currency} receipt spending`}>
      <h3>{entry.currency}</h3>
      <dl className="receipt-stat-summary">
        <div><dt>Receipt totals</dt><dd>{money(entry.total, entry.currency)}</dd></div>
        <div><dt>Net item spending</dt><dd>{money(entry.item_total, entry.currency)}</dd></div>
        <div><dt>Matched receipts</dt><dd>{entry.linked_count} of {entry.receipt_count}</dd></div>
      </dl>
      <div className="receipt-stat-lists">
        <section>
          <h4>By category</h4>
          <Breakdown rows={entry.categories} currency={entry.currency}
            truncated={entry.categories_truncated} empty="No categorized items." />
        </section>
        <section>
          <h4>By product</h4>
          <Breakdown rows={entry.products} currency={entry.currency}
            truncated={entry.products_truncated} empty="No products." />
        </section>
      </div>
    </section>)}
  </>;
}

ReceiptStatistics.propTypes = { statistics: PropTypes.arrayOf(PropTypes.shape({
  currency: PropTypes.string.isRequired, total: PropTypes.string.isRequired, item_total: PropTypes.string.isRequired,
  receipt_count: PropTypes.number.isRequired, linked_count: PropTypes.number.isRequired,
  categories: breakdown.isRequired, categories_truncated: PropTypes.bool.isRequired,
  products: breakdown.isRequired, products_truncated: PropTypes.bool.isRequired,
})).isRequired };
