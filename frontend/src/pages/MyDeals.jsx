import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { FiArrowRight, FiBell, FiHeart, FiTag } from "react-icons/fi";
import toast from "react-hot-toast";
import api from "../api";
import { DashboardError, DashboardLoading } from "../components/DashboardFeedback";
import { RetailerMark } from "../components/GroceryBasketResults";
import DealCard from "../components/myDeals/DealCard";
import { useNotificationInbox } from "../components/notificationContext";
import { displayDate } from "../copilotPresentation";
import { addCatalogPackage, groceryDraft, storeGroceryDraft } from "../groceryDraft";
import { expiresSoon, lowerThanReceipt, uniqueOffers } from "../personalizedDeals";
import { receiptApiError } from "../receiptScanner";
import "../styles/pages/GroceryOptimizer.css";
import "../styles/pages/MyDeals.css";

const productsPath = "/api/grocery/my-products/";
const dealsPath = "/api/grocery/personalized-deals/";
const sections = [
  ["all", "Deals for you"], ["price", "Price drops"], ["soon", "Offers expiring soon"], ["review", "Needs review"],
];
const descriptions = {
  all: "Matching supermarket offers based on your saved interests.",
  price: "Advertised unit prices below what you paid on a comparable confirmed receipt.",
  soon: "Current offers ending by tomorrow, or within 48 hours when the retailer lists an exact time.",
  review: "Check the offer details before accepting an uncertain alternative.",
};
const empty = {
  all: "No matching deals in the current catalog. Try another currency or update your saved products.",
  price: "No current offers are below a comparable receipt price. A confirmed purchase and receipt personalization are needed for this comparison.",
  soon: "No matching offers are ending soon.",
  review: "There are no uncertain deals to review.",
};

export default function MyDeals() {
  const { account } = useNotificationInbox();
  const [library, setLibrary] = useState(null);
  const [response, setResponse] = useState(null);
  const [version, setVersion] = useState(0);
  const [currency, setCurrency] = useState("EUR");
  const [membership, setMembership] = useState([]);
  const [section, setSection] = useState("all");
  const [visible, setVisible] = useState(12);
  const [added, setAdded] = useState(() => new Set(groceryDraft(account)?.items.map((item) => item.offer_id)));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const mutation = useRef(null);
  const key = JSON.stringify([currency, membership, version]);
  const deals = response?.key === key ? response : null;

  useEffect(() => () => mutation.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController();
    api.get(productsPath, { signal: controller.signal, timeout: 12000 })
      .then(({ data }) => { if (!controller.signal.aborted) setLibrary({ data }); })
      .catch(() => { if (!controller.signal.aborted) setLibrary({ error: "Your product preferences could not load." }); });
    return () => controller.abort();
  }, [version]);

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ currency, include_review: "true" });
    membership.forEach((id) => params.append("membership_retailers", id));
    api.get(dealsPath, { params, signal: controller.signal, timeout: 15000 })
      .then(({ data }) => { if (!controller.signal.aborted) setResponse({ key, data }); })
      .catch(() => { if (!controller.signal.aborted) setResponse({ key, error: "Your personalized deals could not load." }); });
    return () => controller.abort();
  }, [currency, key, membership]);

  const refresh = () => setVersion((value) => value + 1);
  async function act(work, message, update = true) {
    if (mutation.current) return;
    const controller = new AbortController();
    mutation.current = controller;
    setBusy(true);
    setError("");
    try {
      await work({ signal: controller.signal, timeout: 12000 });
      if (controller.signal.aborted) return;
      if (update) refresh();
      toast.success(message);
    } catch (failure) {
      if (!controller.signal.aborted) setError(receiptApiError(failure, failure.message || "Could not complete this action. Try again."));
    } finally {
      if (mutation.current === controller) mutation.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  function saveSettings(changes, message) {
    act(async (options) => {
      const { data } = await api.patch(`${productsPath}settings/`, changes, options);
      if (!options.signal.aborted) setLibrary((current) => current?.data ? { data: { ...current.data, settings: data } } : current);
    }, message);
  }

  function add(offer) {
    act(async (options) => {
      const { data } = await api.get(`/api/grocery/catalog/${offer.offer_id}/`, options).catch((failure) => {
        if (failure.response?.status === 404) throw new Error("This offer has expired or is no longer in the current catalog.");
        throw failure;
      });
      if (options.signal.aborted) return;
      const next = addCatalogPackage(groceryDraft(account), data);
      if (next.error) throw new Error(next.error);
      if (!storeGroceryDraft(account, next)) throw new Error("The browser could not save your shopping list.");
      setAdded(new Set(next.items.map((item) => item.offer_id)));
    }, "Added to your shopping list", false);
  }

  const settings = library?.data?.settings;
  const products = library?.data?.products ?? [];
  const favorites = products.filter((product) => product.favorite && !product.excluded);
  const frequent = [
    ...products.filter((product) => !product.excluded && product.purchase_frequency >= 3),
    ...(library?.data?.suggestions ?? []),
  ].sort((a, b) => b.purchase_frequency - a.purchase_frequency).slice(0, 6);
  const interests = deals?.data?.interests ?? [];
  const offers = uniqueOffers(interests);
  const view = {
    all: offers, price: offers.filter(lowerThanReceipt), soon: offers.filter((offer) => expiresSoon(offer)),
    review: uniqueOffers(interests, "review"),
  };
  const retailerStatus = deals?.data?.retailers ?? [];
  const noFresh = retailerStatus.length > 0 && retailerStatus.every((row) => row.status !== "fresh");
  const stale = retailerStatus.some((row) => row.status === "stale");

  return <main className="grocery-page my-deals-page">
    <header className="grocery-hero my-deals-hero">
      <span className="grocery-hero-icon"><FiTag aria-hidden="true" /></span>
      <div><h1>My Deals</h1><p>Find offers for products you already shop for.</p></div>
      <div className="dash-actions">
        <Link className="dash-button" to="/promotions">All promotions</Link>
        <Link className="dash-button dash-primary" to="/grocery">Open shopping list <FiArrowRight aria-hidden="true" /></Link>
      </div>
    </header>
    {error && <p className="my-deals-status" role="alert">{error}</p>}

    <div className="my-deals-layout">
      <section className="grocery-panel my-deals-results" aria-labelledby="my-deals-results">
        <div className="grocery-section-heading"><h2 id="my-deals-results">Deals for you</h2>
          <label>Currency <select value={currency} onChange={(event) => { setCurrency(event.target.value); setVisible(12); }}>
            <option value="EUR">EUR</option><option value="BGN">BGN</option>
          </select></label>
        </div>
        {!deals ? <DashboardLoading label="Loading personalized deals" /> : deals.error
          ? <DashboardError onRetry={refresh}>{deals.error}</DashboardError> : <>
            <div className="my-deals-retailers" aria-label="Retailer catalog status">
              {retailerStatus.map((row) => <div key={row.retailer} data-status={row.status}>
                <RetailerMark id={row.retailer} />
                <span>{row.status === "unavailable" ? "Data unavailable" : row.status === "stale" ? "Stale data"
                  : row.refresh_failed ? "Latest refresh failed" : "Catalog current"}</span>
                {row.last_success_at && <time className="my-deals-muted" dateTime={row.last_success_at}>
                  Updated {displayDate(row.last_success_at.slice(0, 10))}
                </time>}
              </div>)}
            </div>
            {noFresh && <p className="my-deals-status" role="status">
              {stale ? "Catalog data is stale. Older offers are hidden until a retailer refresh succeeds."
                : "Retailer data is unavailable. Matching deals will appear after the first successful catalog refresh."}
            </p>}
            {!interests.length ? <div className="my-deals-empty">
              <FiHeart aria-hidden="true" /><h3>No active product preferences</h3>
              <p>Save a product or approve a receipt suggestion to personalize this page.</p>
              <Link className="dash-button" to="/my-products">Manage My Products</Link>
            </div> : <>
              <div className="my-deals-filters" role="group" aria-label="Filter personalized offers">
                {sections.map(([value, label]) => <button key={value} type="button" aria-pressed={section === value}
                  onClick={() => { setSection(value); setVisible(12); }}>{label} <span>{view[value].length}</span></button>)}
              </div>
              <p className="my-deals-muted">{descriptions[section]}</p>
              {!view[section].length && !noFresh && <p className="my-deals-empty" role="status">{empty[section]}</p>}
              {!!view[section].length && <div className="my-deal-grid">
                {view[section].slice(0, visible).map((offer) => {
                  const saved = products.find((product) => product.product === offer.offer_id || product.normalized_name === offer.normalized_name);
                  const favorite = Boolean(saved?.favorite && !saved.excluded);
                  const mutedProduct = saved ?? offer.interest;
                  return <DealCard key={offer.offer_id} offer={offer} favorite={favorite} muteName={mutedProduct.name}
                    added={added.has(offer.offer_id)} busy={busy || !settings} preferredStores={settings?.preferred_retailers ?? []}
                    onAdd={() => add(offer)}
                    onFavorite={() => act((options) => saved
                      ? api.patch(`${productsPath}${saved.id}/`, { favorite: true, excluded: false }, options)
                      : api.post(productsPath, { product: offer.offer_id }, options), "Favorite saved")}
                    onMute={() => act((options) => api.patch(`${productsPath}${mutedProduct.id}/`, { muted: true }, options), "Product muted")}
                    onReview={(decision) => act((options) => api.put(
                      `${dealsPath}${offer.interest.id}/offers/${offer.offer_id}/review/`, { decision }, options,
                    ), decision === "accept" ? "Comparable offer accepted" : "Match rejected")} />;
                })}
              </div>}
              {view[section].length > visible && <button className="dash-button" type="button"
                onClick={() => setVisible((count) => count + 12)}>Show more offers</button>}
              {deals.data.catalog_truncated && <p className="my-deals-muted">The catalog exceeded the search limit. Some current offers may be missing.</p>}
            </>}
            <p className="my-deals-muted">Prices are advertised. Store inventory and prices at checkout can vary.</p>
          </>}
      </section>

      <aside className="my-deals-sidebar" aria-label="Shopping preferences">
        {!library ? <div className="grocery-panel"><DashboardLoading label="Loading shopping preferences" /></div>
          : library.error ? <div className="grocery-panel"><DashboardError onRetry={refresh}>{library.error}</DashboardError></div>
            : <>
              <section className="grocery-panel">
                <h2>Preferred supermarkets</h2>
                <div className="my-deals-stores">
                  {Object.keys(library.data.retailers).map((id) => <label key={id}>
                    <input type="checkbox" checked={settings.preferred_retailers.includes(id)} disabled={busy}
                      onChange={() => {
                        const current = settings.preferred_retailers;
                        const preferred_retailers = current.includes(id) ? current.filter((item) => item !== id) : [...current, id];
                        saveSettings({ preferred_retailers }, "Preferred supermarkets updated");
                      }} />
                    <RetailerMark id={id} />
                  </label>)}
                </div>
                <details className="my-deal-explanation">
                  <summary>Include membership offers</summary>
                  <div className="my-deals-stores">{Object.keys(library.data.retailers).map((id) => <label key={id}>
                    <input type="checkbox" checked={membership.includes(id)} onChange={() => {
                      setMembership((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
                      setVisible(12);
                    }} /><RetailerMark id={id} />
                  </label>)}</div>
                </details>
              </section>
              <section className="grocery-panel">
                <h2>My favorite products</h2>
                {favorites.length ? <ul className="my-deals-product-list">{favorites.map((product) => <li key={product.id}>
                  <span>{product.name}</span>
                  <button type="button" className="dash-button" disabled={busy} onClick={() => act(
                    (options) => api.patch(`${productsPath}${product.id}/`, { muted: !product.muted }, options),
                    product.muted ? "Product unmuted" : "Product muted",
                  )}>{product.muted ? "Unmute" : "Mute"} <span className="my-deals-sr">{product.name}</span></button>
                </li>)}</ul> : <p className="my-deals-muted">Your saved favorites will appear here.</p>}
                <Link className="dash-link" to="/my-products">Manage products</Link>
              </section>
              <section className="grocery-panel">
                <h2>Frequently purchased products</h2>
                {!settings.automatic_enabled ? <p className="my-deals-muted">Enable receipt personalization in My Products to see purchase patterns.</p>
                  : !frequent.length ? <p className="my-deals-muted">No frequent staples from confirmed receipts yet.</p>
                    : <ul className="my-deals-product-list">{frequent.map((product) => <li key={product.normalized_name}>
                      <strong>{product.name}</strong><small>{product.purchase_frequency} purchase days</small>
                    </li>)}</ul>}
                <Link className="dash-link" to="/my-products">Review receipt suggestions</Link>
              </section>
              <section className="grocery-panel">
                <h2><FiBell aria-hidden="true" /> Notification settings</h2>
                <label className="my-deals-alert-toggle"><input type="checkbox" checked={settings.deal_alerts_enabled} disabled={busy}
                  onChange={() => saveSettings({ deal_alerts_enabled: !settings.deal_alerts_enabled },
                    settings.deal_alerts_enabled ? "Deal alerts disabled" : "Deal alerts enabled")} /> In-app deal alerts</label>
                {settings.deal_alerts_enabled && <p className="my-deals-muted">{settings.deal_delivery === "digest" ? "Daily digest" : "Individual alerts"} · {products.filter(
                  ({ notifications_enabled, excluded, muted }) => notifications_enabled && !excluded && !muted,
                ).length} products enabled</p>}
                <Link className="dash-link" to="/my-products#deal-alert-settings">Manage delivery and quiet hours</Link>
              </section>
            </>}
      </aside>
    </div>
  </main>;
}
