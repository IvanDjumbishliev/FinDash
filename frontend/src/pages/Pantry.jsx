import { useEffect, useState } from "react";
import PropTypes from "prop-types";
import { Link } from "react-router-dom";
import toast from "react-hot-toast";
import api from "../api";
import { DashboardLoading } from "../components/DashboardFeedback";
import { useNotificationInbox } from "../components/notificationContext";
import { money } from "../copilotPresentation";
import { addPantryReplenishment, groceryDraft, storeGroceryDraft } from "../groceryDraft";
import { retailers } from "../groceryOptimizer";
import { receiptApiError } from "../receiptScanner";
import "../styles/pages/Pantry.css";

const endpoint = "/api/pantry/";
const empty = {
  name: "", brand: "", quantity: null, unit: "item", quantity_confirmed: false,
  expires_on: null, replenish_below: null, track_deals: false,
};
const pantryItem = PropTypes.shape({
  id: PropTypes.number, name: PropTypes.string.isRequired, brand: PropTypes.string,
  quantity: PropTypes.string, unit: PropTypes.string, quantity_confirmed: PropTypes.bool,
  expires_on: PropTypes.string, replenish_below: PropTypes.string, track_deals: PropTypes.bool,
});
const units = { kg: "kg", l: "L", item: "items" };

function PantryForm({ item, close, saved }) {
  const [form, setForm] = useState(() => Object.fromEntries(
    Object.keys(empty).map((key) => [key, item ? item[key] : empty[key]]),
  ));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  function edit(key, value) {
    setForm((previous) => ({
      ...previous, [key]: value,
      ...(["quantity", "unit"].includes(key) ? { quantity_confirmed: false } : {}),
      ...(key === "unit" ? { quantity: null, replenish_below: null } : {}),
    }));
  }
  async function save(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (item) await api.patch(`${endpoint}${item.id}/`, form, { timeout: 10000 });
      else await api.post(endpoint, form, { timeout: 10000 });
      saved(item ? "Pantry item updated." : "Item added to your pantry.");
    } catch (failure) {
      setError(receiptApiError(failure, "Could not save this pantry item."));
    } finally {
      setBusy(false);
    }
  }
  return <form className="dash-panel pantry-form" onSubmit={save}>
    <h2>{item ? `Edit ${item.name}` : "Add a pantry item"}</h2>
    <fieldset disabled={busy}>
      <label>Product name <input value={form.name} maxLength={180} required onChange={(event) => edit("name", event.target.value)} /></label>
      <label>Brand (optional) <input value={form.brand} maxLength={120} onChange={(event) => edit("brand", event.target.value)} /></label>
      <label>Unit <select value={form.unit} onChange={(event) => edit("unit", event.target.value)}>
        <option value="">Unknown</option>
        {Object.entries(units).map(([unit, label]) => <option key={unit} value={unit}>{label}</option>)}
      </select></label>
      <label>Quantity on hand <input type="number" min="0" max="1000" step={form.unit === "item" ? "1" : "0.000001"}
        value={form.quantity ?? ""} onChange={(event) => edit("quantity", event.target.value || null)} /></label>
      <label>Replenish at or below <input type="number" min="0" max="1000" step={form.unit === "item" ? "1" : "0.000001"}
        value={form.replenish_below ?? ""} onChange={(event) => edit("replenish_below", event.target.value || null)} /></label>
      <label>Expiration date (optional) <input type="date" value={form.expires_on ?? ""}
        onChange={(event) => edit("expires_on", event.target.value || null)} /></label>
      <label className="pantry-check"><input type="checkbox" checked={form.quantity_confirmed}
        disabled={form.quantity == null} onChange={(event) => edit("quantity_confirmed", event.target.checked)} /> I checked the quantity on hand</label>
      <label className="pantry-check"><input type="checkbox" checked={form.track_deals}
        onChange={(event) => edit("track_deals", event.target.checked)} /> Track advertised deals for this item</label>
    </fieldset>
    {error && <p role="alert">{error}</p>}
    <div className="dash-actions">
      <button type="submit" className="dash-button dash-primary" disabled={busy}>{busy ? "Saving…" : "Save pantry item"}</button>
      <button type="button" className="dash-button" disabled={busy} onClick={close}>Cancel</button>
    </div>
  </form>;
}

PantryForm.propTypes = { item: pantryItem, close: PropTypes.func.isRequired, saved: PropTypes.func.isRequired };

function readData(path, setState, params) {
  const controller = new AbortController();
  api.get(path, { params, signal: controller.signal, timeout: 10000 })
    .then(({ data }) => { if (!controller.signal.aborted) setState({ data }); })
    .catch((error) => {
      if (!controller.signal.aborted) setState({ error: receiptApiError(error, "Could not load this pantry information.") });
    });
  return () => controller.abort();
}

function PantryInsights({ path, item, close }) {
  const [state, setState] = useState(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => readData(path, setState), [path, revision]);
  return <section className="dash-panel pantry-insights">
    <h2>{item ? `Advertised offers for ${item.name}` : "Recipe ideas"}</h2>
    {item ? <p>Prices are advertised and availability may vary.</p>
      : <p>Ideas use items with confirmed quantities above zero. Check that you have enough of each ingredient.</p>}
    {!state ? <DashboardLoading label="Loading pantry insights" /> : state.error
      ? <p role="alert">{state.error} <button type="button" onClick={() => { setState(null); setRevision(revision + 1); }}>Retry</button></p>
      : item ? <>
        {state.data.offers.length ? <ul className="pantry-results">{state.data.offers.map(({ package: offer, relation }) =>
          <li key={offer.id}><strong>{offer.name}</strong> · {retailers[offer.retailer]?.name} · {money(offer.price, offer.currency)}
            <small>{relation === "exact" ? "Exact match" : "Comparable offer"} · Offer ends {offer.expires_on}</small></li>)}</ul>
          : <p>No current public offers match this item.</p>}
        {state.data.retailers.some(({ status }) => status !== "fresh") && <p>Some retailer data is stale or unavailable.</p>}
        {state.data.catalog_truncated && <p>The offer search covered the latest part of the catalog.</p>}
      </> : state.data.length ? <ul className="pantry-results">
        {state.data.map((idea) => <li key={idea.name}><strong>{idea.name}</strong><small>{idea.ingredients.join(", ")}</small></li>)}
      </ul> : <p>No ideas match your confirmed ingredients yet.</p>}
    <button type="button" className="dash-button" onClick={close}>Close</button>
  </section>;
}

PantryInsights.propTypes = { path: PropTypes.string.isRequired, item: pantryItem, close: PropTypes.func.isRequired };

function ReplenishForm({ item, account, close }) {
  const [quantity, setQuantity] = useState("");
  const [error, setError] = useState("");
  return <form className="pantry-replenish" onSubmit={(event) => {
    event.preventDefault();
    const next = addPantryReplenishment(groceryDraft(account), item, quantity);
    if (next.error) setError(next.error);
    else if (!storeGroceryDraft(account, next)) setError("Could not save your shopping draft in this browser.");
    else { toast.success("Added to your grocery basket draft."); close(); }
  }}>
    <label>Quantity to buy ({units[item.unit]}) <input type="number" value={quantity} required
      min={item.unit === "item" ? "1" : "0.000001"} max="1000" step={item.unit === "item" ? "1" : "0.000001"} onChange={(event) => setQuantity(event.target.value)} /></label>
    <button type="submit" className="dash-button">Add to draft</button>
    <button type="button" className="dash-button" onClick={close}>Cancel</button>
    {error && <p role="alert">{error}</p>}
  </form>;
}

ReplenishForm.propTypes = {
  item: pantryItem.isRequired, account: PropTypes.oneOfType([PropTypes.number, PropTypes.string]), close: PropTypes.func.isRequired,
};

export default function Pantry() {
  const { account } = useNotificationInbox();
  const [data, setData] = useState(null);
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [editing, setEditing] = useState(null);
  const [insights, setInsights] = useState(null);
  const [replenishing, setReplenishing] = useState(null);
  const [removing, setRemoving] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => readData(endpoint, setData, { page }), [page, revision]);

  function refresh() { setData(null); setRevision((value) => value + 1); }
  function saved(message) {
    toast.success(message);
    setEditing(null);
    setInsights(null);
    refresh();
  }
  async function remove() {
    setBusy(true);
    setError("");
    try {
      await api.delete(`${endpoint}${removing}/`, { timeout: 10000 });
      setRemoving(null);
      if (data?.data?.results.length === 1 && page > 1) setPage(page - 1);
      saved("Pantry item removed.");
    } catch (failure) {
      setError(receiptApiError(failure, "Could not remove this pantry item."));
    } finally { setBusy(false); }
  }

  return <main className="dashboard-shell pantry-page">
    <header className="dash-header">
      <h1>Smart Pantry</h1>
      <p>Keep track of what you have. Receipt quantities are estimates until you check them. Recorded expiration dates do not determine food safety.</p>
      <div className="dash-actions">
        <button type="button" className="dash-button dash-primary" onClick={() => setEditing("new")}>Add pantry item</button>
        <button type="button" className="dash-button" onClick={() => setInsights({ path: `${endpoint}recipes/` })}>Find recipe ideas</button>
        <Link className="dash-link" to="/receipts/history">Add from a saved receipt</Link>
        <Link className="dash-link" to="/grocery">Open grocery basket</Link>
      </div>
    </header>
    {editing && <PantryForm key={editing.id ?? "new"} item={editing === "new" ? undefined : editing}
      close={() => setEditing(null)} saved={saved} />}
    {error && <p role="alert">{error}</p>}
    {insights && <PantryInsights key={insights.path} {...insights} close={() => setInsights(null)} />}
    {!data ? <DashboardLoading label="Loading pantry" /> : data.error
      ? <p role="alert">{data.error} <button type="button" onClick={refresh}>Retry</button></p>
      : data.data.results.length ? <>
        <ul className="pantry-items">
          {data.data.results.map((item) => <li className="dash-panel" key={item.id}>
            <h2>{item.name}</h2>
            {item.brand && <p>{item.brand}</p>}
            <p>{item.quantity == null ? "Quantity unknown" :
              `${Number(item.quantity)} ${units[item.unit]} · ${item.quantity_confirmed ? "Confirmed" : "Estimated"}`}</p>
            {item.expires_on && <p>Recorded expiration date · <time dateTime={item.expires_on}>{item.expires_on}</time></p>}
            {item.needs_replenishment && <p>{item.quantity_confirmed ? "At or below your replenishment level." : "May need replenishment. Check the estimated quantity."}</p>}
            <div className="dash-actions">
              <button type="button" className="dash-button" onClick={() => setEditing(item)}>Edit quantity or details</button>
              {item.unit && <button type="button" className="dash-button" onClick={() => setReplenishing(item.id)}>Add to shopping list</button>}
              {item.track_deals && <button type="button" className="dash-button" onClick={() => setInsights({ item, path: `${endpoint}${item.id}/deals/` })}>Find deals</button>}
              <button type="button" className="dash-button" onClick={() => { setRemoving(item.id); setError(""); }}>Remove</button>
            </div>
            {replenishing === item.id && <ReplenishForm item={item} account={account} close={() => setReplenishing(null)} />}
            {removing === item.id && <div className="dash-actions">
              <span>Remove this item from your pantry?</span>
              <button type="button" className="dash-button" disabled={busy} onClick={remove}>Confirm removal</button>
              <button type="button" className="dash-button" disabled={busy} onClick={() => setRemoving(null)}>Keep item</button>
            </div>}
          </li>)}
        </ul>
        {(data.data.previous || data.data.next) && <nav className="dash-actions" aria-label="Pantry pages">
          <button type="button" disabled={!data.data.previous} onClick={() => { setData(null); setPage(page - 1); }}>Previous</button>
          <span>Page {page}</span>
          <button type="button" disabled={!data.data.next} onClick={() => { setData(null); setPage(page + 1); }}>Next</button>
        </nav>}
      </> : <section className="dash-panel"><h2>Your pantry is empty</h2><p>Add an item manually or choose one from a confirmed receipt.</p></section>}
  </main>;
}
