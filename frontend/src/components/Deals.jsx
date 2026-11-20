import { useEffect, useState } from "react";
import "../styles/components/Deals.css";
import kaufland from "../assets/kaufland.png";
import lidl from "../assets/lidl.png";
import api from "../api";

const stores = [
  { id: "kaufland", name: "Kaufland", image: kaufland },
  { id: "lidl", name: "Lidl", image: lidl },
  { id: "fantastico", name: "Fantastico" },
];

const StoreItemGrid = ({ items }) => (
  <div className="deal-items-grid">
    {items.map((item, index) => (
      <article className="deal-item deal-card" key={`${item.name}-${item.price}-${index}`}>
        {item.image_url && (
          <img
            className="deal-card-image"
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
          <div className="deal-card-prices">
            {item.price && <span className="deal-value">{item.price}</span>}
            {item.discount_percent > 0 && (
              <span className="deal-savings">−{item.discount_percent}%</span>
            )}
          </div>
        </div>
      </article>
    ))}
  </div>
);

const Deals = ({ isFetched }) => {
  const [activeStore, setActiveStore] = useState(stores[0]);
  const [results, setResults] = useState({});
  const result = results[activeStore.id];

  useEffect(() => {
    const controller = new AbortController();
    const requests = stores.map(async ({ id }) => {
      let storeResult;
      try {
        const { data } = await api.get(`/api/deals/${id}/`, {
          signal: controller.signal,
        });
        storeResult = Array.isArray(data) ? { items: data } : { error: true };
      } catch {
        storeResult = { error: true };
      }
      if (!controller.signal.aborted) {
        setResults((previous) => ({ ...previous, [id]: storeResult }));
      }
    });

    Promise.all(requests).then(() => {
      if (!controller.signal.aborted) {
        isFetched?.();
      }
    });
    return () => controller.abort();
  }, [isFetched]);

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
            {store.image ? (
              <img src={store.image} alt="" />
            ) : (
              <span className="fantastiko-logo">Fantastico</span>
            )}
          </button>
        ))}
      </div>
      <div className="deals-content active" aria-busy={!result}>
        {!result || !result.items?.length ? (
          <p className="deal-empty-state" role="status">
            {!result
              ? `Loading deals from ${activeStore.name}…`
              : result.error
                ? `Could not load deals from ${activeStore.name}.`
                : `No current offers could be loaded for ${activeStore.name}.`}
          </p>
        ) : (
          <StoreItemGrid key={activeStore.id} items={result.items} />
        )}
      </div>
    </section>
  );
};

export default Deals;
