import { useState } from "react";
import PropTypes from "prop-types";
import { FiArrowUpRight, FiCheckSquare, FiShoppingBag } from "react-icons/fi";
import { displayDate, money } from "../copilotPresentation";
import { retailers, units } from "../groceryOptimizer";

export function RetailerMark({ id }) {
  const store = retailers[id];
  return store ? <span className="grocery-retailer-mark">
    <img src={store.image} alt="" />{store.name}
  </span> : null;
}
RetailerMark.propTypes = { id: PropTypes.string.isRequired };

export function ProductImage({ src }) {
  const [failed, setFailed] = useState(false);
  const safe = typeof src === "string" && /^https?:\/\//i.test(src);
  return <span className="grocery-product-image">
    {safe && !failed ? <img src={src} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
      : <FiShoppingBag aria-hidden="true" />}
  </span>;
}
ProductImage.propTypes = { src: PropTypes.string };

function PriceCard({ title, basket, currency, highlight }) {
  const total = basket?.estimated_total;
  return <div className={`grocery-price-card${highlight ? " grocery-price-highlight" : ""}`}>
    <h3>{title}</h3>
    <strong>{total == null ? "Incomplete" : money(total, currency)}</strong>
    {basket?.retailers_used.length > 0 && <div className="grocery-plan-stores">
      {basket.retailers_used.map((id) => <RetailerMark key={id} id={id} />)}
    </div>}
    {basket && !basket.complete && <p>{basket.unmatched_item_indexes.length} unmatched · {money(basket.matched_items_subtotal, currency)} matched subtotal</p>}
    {!basket && <p>No complete basket in the selected catalog.</p>}
    {basket?.complete && <p>Includes {money(basket.overhead_cost, currency)} shopping overhead</p>}
  </div>;
}
PriceCard.propTypes = {
  title: PropTypes.string.isRequired, basket: PropTypes.object, currency: PropTypes.string.isRequired,
  highlight: PropTypes.bool,
};

function Checklist({ basket, result }) {
  const [checked, setChecked] = useState({});
  if (!basket?.lines.length) return <p className="grocery-muted">There are no matched packages to add to the checklist.</p>;
  return <div className="grocery-checklist">
    {basket.retailers_used.map((id) => <section key={id}>
      <h3><RetailerMark id={id} /></h3>
      {basket.lines.flatMap((line) => line.packages.filter((pack) => pack.retailer === id).map((pack) => {
        const key = `${line.item_index}:${pack.offer_id}`;
        const updated = pack.last_successful_update?.slice(0, 10);
        return <div key={key} className={checked[key] ? "grocery-check checked" : "grocery-check"}>
          <input id={`shopping-pack-${key}`} type="checkbox" checked={Boolean(checked[key])}
            onChange={() => setChecked((previous) => ({ ...previous, [key]: !previous[key] }))} />
          <ProductImage src={pack.image_url} />
          <div><label htmlFor={`shopping-pack-${key}`}>{pack.count} × {pack.name}</label>
            <small>{pack.quantity_per_package} {units[line.unit]} per pack · {money(pack.package_price, result.currency)} per pack</small>
            {Number(line.surplus_quantity) > 0 && <small>Line surplus {line.surplus_quantity} {units[line.unit]}</small>}
            <small>{updated ? `Observed ${displayDate(updated)}` : "Observation date unavailable"} · {pack.expires_on ? `Offer ends ${displayDate(pack.expires_on)}` : "End date unavailable"}</small>
            {/^https?:\/\//i.test(pack.source_url ?? "") && <a href={pack.source_url} target="_blank" rel="noreferrer">
              Offer source <FiArrowUpRight aria-hidden="true" /></a>}
          </div>
          <strong>{money(pack.estimated_cost, result.currency)}</strong>
        </div>;
      }))}
    </section>)}
  </div>;
}
Checklist.propTypes = { basket: PropTypes.object, result: PropTypes.object.isRequired };

export default function GroceryBasketResults({ result }) {
  const { currency, savings, single_retailer_baskets: singles, multi_retailer_basket: multi } = result;
  const lowestSingle = (savings && singles.find((basket) => basket.retailers_used[0] === savings.reference_retailer))
    || singles.filter((basket) => basket.complete).sort((a, b) => Number(a.estimated_total) - Number(b.estimated_total))[0];
  const [selection, setSelection] = useState("recommended");
  const recommended = result.best_basket ?? result.best_partial_basket;
  const basket = selection === "recommended" ? recommended : singles.find((plan) => plan.allowed_retailers[0] === selection);
  const unmatched = basket?.unmatched_item_indexes ?? [];

  return <section className="grocery-results" aria-labelledby="grocery-results-heading">
    <div className="grocery-section-heading">
      <div><h2 id="grocery-results-heading">Basket comparison</h2>
        <p className="grocery-muted">Estimated costs from advertised offers · {displayDate(result.as_of.slice(0, 10))}</p></div>
    </div>
    <div className="grocery-price-grid">
      <PriceCard title="Lowest estimated single-store basket" basket={lowestSingle} currency={currency} />
      {multi && <PriceCard title={multi.retailers_used.length > 1 ? "Optimized multi-store basket" : "Optimized basket · multiple stores allowed"}
        basket={multi} currency={currency} highlight />}
      <div className="grocery-price-card grocery-savings">
        <h3>Estimated savings</h3>
        <strong>{savings ? money(savings.estimated_savings, currency) : "Unavailable"}</strong>
        <p>{savings ? `Compared with the ${retailers[savings.reference_retailer].name} complete basket at ${money(savings.reference_total, currency)}, including overhead.`
          : "Savings require a complete single-store comparison basket."}</p>
      </div>
    </div>
    {!result.best_basket && <p className="grocery-warning">No complete basket was found. Matched subtotals cover only the items listed for each plan.</p>}
    <div className="grocery-panel">
      <h3>Product-by-product comparison</h3>
      <p className="grocery-muted">Estimated whole-package cost by retailer, before overhead.</p>
      <div className="grocery-table-scroll" tabIndex={0} role="region" aria-label="Product costs by retailer">
        <table>
          <thead><tr><th scope="col">Shopping item</th>{singles.map((plan) =>
            <th scope="col" key={plan.allowed_retailers[0]}><RetailerMark id={plan.allowed_retailers[0]} /></th>)}</tr></thead>
          <tbody>{result.items.map((item) => <tr key={item.index}>
            <th scope="row">{item.name}<small>{item.quantity} {units[item.unit]}</small></th>
            {singles.map((plan) => {
              const row = plan.lines.find((line) => line.item_index === item.index);
              return <td key={plan.allowed_retailers[0]}>{row ? <>
                <strong>{money(row.estimated_cost, currency)}</strong>
                <small>{row.packages.map((pack) => `${pack.count} × ${pack.quantity_per_package} ${units[row.unit]}`).join(" + ")}</small>
              </> : "Unmatched"}</td>;
            })}
          </tr>)}</tbody>
        </table>
      </div>
      {result.items.some((item) => item.excluded_offers.offers.length > 0) && <details className="grocery-diagnostics">
        <summary>Excluded offer details</summary>
        {result.items.filter((item) => item.excluded_offers.offers.length).map((item) => <div key={item.index}>
          <h4>{item.name}</h4>
          <ul>{item.excluded_offers.offers.map((offer) => <li key={offer.offer_id}>
            {offer.name} · {retailers[offer.retailer].name} · <strong>{offer.status}</strong>
            {offer.expires_on && ` · Offer end ${displayDate(offer.expires_on)}`}
          </li>)}</ul>
          {item.excluded_offers.truncated && <p className="grocery-muted">Additional excluded offers were omitted.</p>}
        </div>)}
      </details>}
    </div>

    <section className="grocery-panel" aria-labelledby="grocery-checklist-heading">
      <div className="grocery-section-heading">
        <div><h3 id="grocery-checklist-heading"><FiCheckSquare aria-hidden="true" /> Shopping checklist</h3>
          <p className="grocery-muted">Advertised prices and dates can change. Store inventory is unverified.</p></div>
        <label>Basket<select value={selection} onChange={(event) => setSelection(event.target.value)}>
          <option value="recommended">Suggested basket</option>
          {singles.map((plan) => <option key={plan.allowed_retailers[0]} value={plan.allowed_retailers[0]}>
            {retailers[plan.allowed_retailers[0]].name}
          </option>)}
        </select></label>
      </div>
      {unmatched.length > 0 && <p className="grocery-warning">Unmatched in this basket: {unmatched.map((index) => result.items[index].name).join(", ")}.</p>}
      <Checklist key={selection} basket={basket} result={result} />
    </section>
    <details className="grocery-panel"><summary>How these estimates are calculated</summary>
      <ul>{result.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}</ul>
    </details>
  </section>;
}
GroceryBasketResults.propTypes = { result: PropTypes.object.isRequired };
