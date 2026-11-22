import { dealItems, dealResults, storeList } from "./dealProps";
import { useState } from "react";
import "../styles/components/Deals.css";

export const StoreItemGrid = ({ items }) => (
  <div className="deal-items-grid">
    {items.map((item, index) => (
      <article className="deal-item deal-card" key={`${item.name}-${item.price}-${index}`}>
        {item.image_url && (
          <img
            className="deal-card-image"
            key={item.image_url}
            src={item.image_url}
            alt=""
            loading="lazy"
            onError={(event) => {
              event.currentTarget.hidden = true;
            }}
          />
        )}
        <div className="deal-card-copy">
          <span className="deal-name">{item.name}</span>
          {item.storeName && <span className="deal-store">{item.storeName}</span>}
          <div className="deal-card-prices">
            {item.price && <span className="deal-value">{item.price}</span>}
            {item.price_note && <span className="deal-store">{item.price_note}</span>}
            {item.discount_percent > 0 && (
              <span className="deal-savings">−{item.discount_percent}%</span>
            )}
          </div>
        </div>
      </article>
    ))}
  </div>
);

const Deals = ({ stores, results }) => {
  const [activeStore, setActiveStore] = useState(stores[0]);
  const result = results[activeStore.id];

  return (
    <section className="deals-container" aria-labelledby="deals-title">
      <h2 id="deals-title">Best deals right now</h2>
      <div className="deal-store-picker" role="group" aria-label="Choose a store">
        {stores.map((store) => (
          <button
            key={store.id}
            type="button"
            className={`button ${activeStore.id === store.id ? "active" : ""}`}
            aria-label={store.name}
            aria-pressed={activeStore.id === store.id}
            onClick={() => setActiveStore(store)}
          >
            <img src={store.image} alt="" />
          </button>
        ))}
      </div>
      <div
        key={activeStore.id}
        className="deals-content"
        role="region"
        aria-label={`${activeStore.name} offers`}
        aria-busy={!result}
        tabIndex={0}
      >
        {!result || !result.items?.length ? (
          <p className="deal-empty-state" role="status">
            {!result
              ? `Loading deals from ${activeStore.name}…`
              : result.error
                ? `Could not load deals from ${activeStore.name}.`
                : `No current offers could be loaded for ${activeStore.name}.`}
            {result && activeStore.offerUrl && <> <a href={activeStore.offerUrl}>View official offers</a></>}
          </p>
        ) : (
          <StoreItemGrid items={result.items} />
        )}
      </div>
    </section>
  );
};

export default Deals;

Deals.propTypes = { stores: storeList.isRequired, results: dealResults.isRequired };
StoreItemGrid.propTypes = { items: dealItems.isRequired };
