import { useEffect, useRef, useState } from "react";
import PropTypes from "prop-types";
import { FiHeart, FiTag } from "react-icons/fi";
import toast from "react-hot-toast";
import api from "../api";
import { displayDate, money } from "../copilotPresentation";
import { receiptApiError } from "../receiptScanner";
import { DashboardLoading, DashboardError } from "../components/DashboardFeedback";
import "../styles/pages/MyProducts.css";

const endpoint = "/api/grocery/my-products/";
const units = { item: "Items", kg: "kg", l: "L" };
const blank = {
  name: "", preferred_brand: "", preferred_quantity: "", preferred_unit: "", minimum_discount: "",
  alert_price: "", alert_currency: "",
  favorite: true, notifications_enabled: false, excluded: false, muted: false,
};

function productFields(value) {
  return {
    ...value,
    preferred_quantity: value.preferred_quantity ?? "",
    minimum_discount: value.minimum_discount ?? "",
    alert_price: value.alert_price ?? "",
  };
}

function ProductEditor({ product, onSave, onCancel, busy }) {
  const [form, setForm] = useState(() => productFields(product || blank));
  const update = (name, value) => setForm((current) => ({ ...current, [name]: value }));

  return <form className="product-editor" onSubmit={(event) => {
    event.preventDefault();
    const fields = {
      preferred_brand: form.preferred_brand.trim(),
      preferred_quantity: form.preferred_quantity === "" ? null : form.preferred_quantity,
      preferred_unit: form.preferred_unit,
      minimum_discount: form.minimum_discount === "" ? null : Number(form.minimum_discount),
      alert_price: form.alert_price === "" ? null : form.alert_price,
      alert_currency: form.alert_currency,
      favorite: form.favorite,
      notifications_enabled: form.notifications_enabled,
      excluded: form.excluded,
      muted: form.muted,
    };
    onSave(product ? fields : { ...fields, name: form.name.trim() });
  }}>
    <fieldset disabled={busy}>
      <div className="product-fields">
        {!product && <label>Product name<input value={form.name} maxLength={255} required
          onChange={(event) => update("name", event.target.value)} /></label>}
        <label>Preferred brand<input value={form.preferred_brand} maxLength={120}
          onChange={(event) => update("preferred_brand", event.target.value)} /></label>
        <label>Preferred package quantity<input value={form.preferred_quantity} type="number" min="0.000001" step="any"
          onChange={(event) => update("preferred_quantity", event.target.value)} /></label>
        <label>Package unit<select value={form.preferred_unit} onChange={(event) => update("preferred_unit", event.target.value)}>
          <option value="">Any unit</option>{Object.entries(units).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select></label>
        <label>Minimum discount (%)<input value={form.minimum_discount} type="number" min="0" max="100"
          onChange={(event) => update("minimum_discount", event.target.value)} /></label>
        <label>Alert at or below<input value={form.alert_price} type="number" min="0.01" step="0.01"
          onChange={(event) => update("alert_price", event.target.value)} /></label>
        <label>Alert currency<select value={form.alert_currency} onChange={(event) => update("alert_currency", event.target.value)}>
          <option value="">Choose currency</option><option value="EUR">EUR</option><option value="BGN">BGN</option>
        </select></label>
      </div>
      <div className="product-toggles">
        {[["favorite", "Favorite"], ["excluded", "Exclude from recommendations"], ["muted", "Mute product"],
          ["notifications_enabled", "Allow deal alerts"]].map(([key, label]) => <label key={key}>
          <input type="checkbox" checked={form[key]} onChange={(event) => update(key, event.target.checked)} /> {label}
        </label>)}
      </div>
      <div className="dash-actions">
        <button className="dash-button dash-primary" type="submit">{busy ? "Saving…" : product ? "Save product" : "Add product"}</button>
        <button className="dash-button" type="button" onClick={onCancel}>Cancel</button>
      </div>
    </fieldset>
  </form>;
}

ProductEditor.propTypes = {
  product: PropTypes.object,
  onSave: PropTypes.func.isRequired,
  onCancel: PropTypes.func.isRequired,
  busy: PropTypes.bool.isRequired,
};

function ProfileSettings({ settings, retailers, categories, onSave, onClear, busy }) {
  const [form, setForm] = useState(settings);
  const update = (key, value) => setForm((current) => ({ ...current, [key]: value }));
  const [confirm, setConfirm] = useState(false);
  const toggle = (key, value) => setForm((current) => ({
    ...current, [key]: current[key].includes(value) ? current[key].filter((item) => item !== value) : [...current[key], value],
  }));
  return <form onSubmit={(event) => { event.preventDefault(); onSave(form); }}>
    <fieldset disabled={busy} className="product-settings-fields">
      <label>
        <input type="checkbox" checked={form.automatic_enabled} onChange={(event) => setForm({ ...form, automatic_enabled: event.target.checked })} />
        {" "}Suggest products I often buy
      </label>
      <p className="product-note">Uses your confirmed FinDash receipts. Preferences stay in FinDash.</p>
      <div className="product-deal-settings">
        <label><input type="checkbox" checked={form.deal_alerts_enabled}
          onChange={(event) => update("deal_alerts_enabled", event.target.checked)} /> Enable in-app deal alerts</label>
        <div className="product-fields">
          <label>Delivery<select value={form.deal_delivery} onChange={(event) => update("deal_delivery", event.target.value)}>
            <option value="individual">Individual alerts</option><option value="digest">Daily digest</option>
          </select></label>
          {form.deal_delivery === "digest" && <label>Digest time<input type="time" value={form.digest_time}
            onChange={(event) => update("digest_time", event.target.value)} required /></label>}
          <label>Quiet hours start<input type="time" value={form.quiet_start ?? ""}
            onChange={(event) => update("quiet_start", event.target.value || null)} /></label>
          <label>Quiet hours end<input type="time" value={form.quiet_end ?? ""}
            onChange={(event) => update("quiet_end", event.target.value || null)} /></label>
        </div>
        <p className="product-note">Times follow your FinDash account timezone. Enable alerts on individual products as well.</p>
      </div>
      {[["preferred_retailers", "Preferred supermarkets", retailers],
        ["category_interests", "Category interests", categories]].map(([key, label, choices]) => <fieldset className="product-choices" key={key}>
        <legend>{label}</legend>
        {Object.entries(choices).map(([value, name]) => <label key={value}>
          <input type="checkbox" checked={form[key].includes(value)} onChange={() => toggle(key, value)} /> {name}
        </label>)}
      </fieldset>)}
      <div className="dash-actions">
        <button className="dash-button dash-primary" type="submit">Save shopping settings</button>
        {!confirm && <button className="dash-button" type="button" onClick={() => setConfirm(true)}>Clear inferred preferences</button>}
      </div>
      {confirm && <div className="product-clear">
        <p>Remove approved and rejected suggestions? Your manually saved products and receipts will stay.</p>
        <button className="dash-button" type="button" onClick={() => { setConfirm(false); onClear(); }}>Clear inferred products</button>
        <button className="dash-button" type="button" onClick={() => setConfirm(false)}>Keep preferences</button>
      </div>}
    </fieldset>
  </form>;
}

ProfileSettings.propTypes = {
  settings: PropTypes.shape({
    automatic_enabled: PropTypes.bool.isRequired,
    deal_alerts_enabled: PropTypes.bool.isRequired,
    deal_delivery: PropTypes.string.isRequired,
    digest_time: PropTypes.string.isRequired,
    quiet_start: PropTypes.string,
    quiet_end: PropTypes.string,
    preferred_retailers: PropTypes.arrayOf(PropTypes.string).isRequired,
    category_interests: PropTypes.arrayOf(PropTypes.string).isRequired,
  }).isRequired,
  retailers: PropTypes.object.isRequired,
  categories: PropTypes.object.isRequired,
  onSave: PropTypes.func.isRequired,
  onClear: PropTypes.func.isRequired,
  busy: PropTypes.bool.isRequired,
};

export default function MyProducts() {
  const [result, setResult] = useState(null);
  const [version, setVersion] = useState(0);
  const [editing, setEditing] = useState(null);
  const [busy, setBusy] = useState(false);
  const [mutationError, setMutationError] = useState("");
  const pending = useRef(null);
  useEffect(() => () => pending.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController();
    api.get(endpoint, { signal: controller.signal, timeout: 12000 })
      .then(({ data }) => { if (!controller.signal.aborted) setResult({ data }); })
      .catch((error) => {
        if (!controller.signal.aborted) setResult({ error: receiptApiError(error, "Could not load your product library.") });
      });
    return () => controller.abort();
  }, [version]);

  async function mutate(method, url, data, success, after) {
    if (pending.current) return;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);
    setMutationError("");
    try {
      await api.request({ method, url, data, signal: controller.signal, timeout: 12000 });
      if (controller.signal.aborted) return;
      after?.();
      setVersion((value) => value + 1);
      toast.success(success);
    } catch (error) {
      if (!controller.signal.aborted) {
        const message = receiptApiError(error, "Could not update your product library. Please try again.");
        setMutationError(message);
        toast.error(message);
      }
    } finally {
      pending.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  const value = result?.data;
  return <main className="dashboard-shell my-products">
    <header className="market-heading">
      <h1>My Products</h1>
      <p>Save products you buy and see matching advertised offers.</p>
    </header>
    {mutationError && <p role="alert" className="product-error">{mutationError}</p>}
    {!result ? <DashboardLoading label="Loading My Products" /> : result.error
      ? <DashboardError onRetry={() => setVersion((value) => value + 1)}>{result.error}</DashboardError>
      : <>
        <div className="product-layout">
          <section className="dash-panel product-panel" aria-labelledby="product-library">
            <div className="product-section-title"><h2 id="product-library">Product library</h2>
              <button type="button" className="dash-button dash-primary" onClick={() => setEditing("new")} disabled={busy}>Add a product</button>
            </div>
            {editing === "new" && <ProductEditor busy={busy} onCancel={() => setEditing(null)}
              onSave={(form) => mutate("post", endpoint, form, "Product added", () => setEditing(null))} />}
            {!value.products.length && editing !== "new" && <p className="product-note">Your library is empty. Add a product to start tracking offers.</p>}
            <ul className="product-list">
              {value.products.map((product) => <li key={product.id}>
                <div className="product-section-title">
                  <h3>{product.favorite && <FiHeart aria-label="Favorite" />} {product.name}</h3>
                  <span>{product.excluded ? "Excluded" : product.muted ? "Muted" : product.source === "inferred" ? "From receipts" : "Manual"}</span>
                </div>
                {product.preferred_brand && <p>Preferred brand: {product.preferred_brand}</p>}
                {product.preferred_quantity && <p>Package: {Number(product.preferred_quantity)} {units[product.preferred_unit]}</p>}
                {product.minimum_discount != null && <p>Minimum discount: {product.minimum_discount}%</p>}
                {product.alert_price != null && <p>Alert at or below {money(product.alert_price, product.alert_currency)}</p>}
                {product.tracked_offers?.map((tracked) => <div key={tracked.offer_id} className="dash-actions product-tracked-offer">
                  <span>{tracked.name} · {value.retailers[tracked.retailer]}</span>
                  <button className="dash-button" type="button" disabled={busy} onClick={() => mutate(
                    "delete", `${endpoint}${product.id}/tracked-offers/${tracked.offer_id}/`, undefined, "Offer untracked",
                  )}>Stop tracking</button>
                </div>)}
                {product.purchase_frequency > 0 && <p className="product-note">
                  {product.purchase_frequency} purchase days in the last recorded {value.lookback_days}-day window
                  {product.last_purchase_date && ` · Last purchased ${displayDate(product.last_purchase_date)}`}
                </p>}
                {editing === product.id ? <ProductEditor product={product} busy={busy}
                  onCancel={() => setEditing(null)} onSave={(form) => mutate("patch", `${endpoint}${product.id}/`, form,
                    "Product updated", () => setEditing(null))} /> : <div className="dash-actions">
                  <button type="button" className="dash-button" disabled={busy} onClick={() => setEditing(product.id)}>Edit {product.name}</button>
                  <button type="button" className="dash-button" disabled={busy} onClick={() => mutate(
                    "delete", `${endpoint}${product.id}/`, undefined, "Product removed",
                  )}>Remove</button>
                </div>}
              </li>)}
            </ul>
          </section>
          <section className="dash-panel product-panel" aria-labelledby="product-settings">
            <h2 id="product-settings">Shopping settings</h2>
            <ProfileSettings settings={value.settings} retailers={value.retailers}
              categories={value.categories} busy={busy}
              onSave={(form) => mutate("patch", `${endpoint}settings/`, form, "Shopping settings saved")}
              onClear={() => mutate("delete", `${endpoint}suggestions/`, undefined, "Inferred preferences cleared")} />
          </section>
        </div>

        <section className="dash-panel product-panel" aria-labelledby="product-suggestions">
          <h2 id="product-suggestions">Suggestions from receipts</h2>
          {!value.settings.automatic_enabled ? <p className="product-note">Turn on receipt-based suggestions in Shopping settings.</p>
            : !value.suggestions.length ? <p className="product-note">No new suggestions. FinDash looks for staple products bought on at least three days.</p>
              : <ul className="product-list">
                {value.suggestions.map((product) => <li key={product.normalized_name}>
                  <h3>{product.name}</h3>
                  <p className="product-note">{product.purchase_frequency} purchase days · Last purchased {displayDate(product.last_purchase_date)}</p>
                  <div className="dash-actions">
                    <button type="button" className="dash-button" disabled={busy} onClick={() => mutate("post",
                      `${endpoint}suggestions/`, { normalized_name: product.normalized_name, decision: "approve" }, "Suggestion approved")}>Approve {product.name}</button>
                    <button type="button" className="dash-button" disabled={busy} onClick={() => mutate("post",
                      `${endpoint}suggestions/`, { normalized_name: product.normalized_name, decision: "reject" }, "Suggestion excluded")}>Reject {product.name}</button>
                  </div>
                </li>)}
              </ul>}
        </section>

        <section className="dash-panel product-panel" aria-labelledby="product-offers">
          <h2 id="product-offers">Matching offers</h2>
          <p className="product-note">Advertised prices from the FinDash catalog. In-store stock can vary.</p>
          {!value.offers.length ? <p className="product-note">No current offers match your products or category interests.</p>
            : <ul className="product-list product-offers">
              {value.offers.map((offer) => {
                const saved = value.products.find((product) => product.normalized_name === offer.normalized_name);
                const tracked = saved?.tracked_offers?.some((row) => row.offer_id === offer.id);
                return <li key={offer.id}>
                <h3><FiTag aria-hidden="true" /> {offer.product_name}</h3>
                <p>{value.retailers[offer.retailer]} · <strong>{money(offer.price, offer.currency)}</strong>
                  {offer.discount_percent != null && ` · ${offer.discount_percent}% off`}</p>
                <p className="product-note">Through {displayDate(offer.expires_on)}
                  {offer.requires_membership && " · Store membership required"}</p>
                {!saved &&
                  <button type="button" className="dash-button" disabled={busy} onClick={() => mutate(
                    "post", endpoint, { product: offer.id }, "Catalog product added",
                  )}>Favorite {offer.product_name}</button>}
                {saved && !offer.requires_membership && <button type="button" className="dash-button"
                  disabled={busy || tracked || !saved.notifications_enabled}
                  onClick={() => mutate("post", `${endpoint}${saved.id}/tracked-offers/`, { offer_id: offer.id }, "Offer tracked")}>
                  {tracked ? "Expiry tracked" : "Track expiry"}
                </button>}
              </li>;
              })}
            </ul>}
        </section>
      </>}
  </main>;
}
