import { useEffect, useRef, useState } from "react";
import { FiArrowRight, FiMinus, FiPlus, FiSearch, FiShoppingCart, FiTrash2 } from "react-icons/fi";
import { Link, useNavigate } from "react-router-dom";
import api from "../api";
import GroceryBasketResults, { ProductImage, RetailerMark } from "../components/GroceryBasketResults";
import { money } from "../copilotPresentation";
import { basketSettings, errorText, retailerIds, units } from "../groceryOptimizer";
import { useNotificationInbox } from "../components/notificationContext";
import { defaultGroceryItem as defaultItem, groceryDraft, storeGroceryDraft } from "../groceryDraft";
import "../styles/pages/GroceryOptimizer.css";

const endpoint = "/api/grocery/";
const initialOptions = { retailers: retailerIds, max_stores: 3, allow_multi_store: true, overhead_per_store: "0.00", currency: "EUR" };

export default function GroceryOptimizer() {
  const navigate = useNavigate();
  const { account } = useNotificationInbox();
  const [draft] = useState(() => groceryDraft(account));
  const [items, setItems] = useState(() => draft?.items || []);
  const [options, setOptions] = useState(() => ({ ...initialOptions, ...draft?.options }));
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState(null);
  const [dropdown, setDropdown] = useState(false);
  const [active, setActive] = useState(-1);
  const [name, setName] = useState("");
  const [saved, setSaved] = useState(null);
  const [invitations, setInvitations] = useState([]);
  const [invitationError, setInvitationError] = useState(false);
  const [savedError, setSavedError] = useState("");
  const [savedRevision, setSavedRevision] = useState(0);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const id = useRef(items.reduce((largest, item) => Math.max(largest, item.id), 0));
  const searchInput = useRef(null);
  const resultsHeading = useRef(null);
  const term = query.trim();
  const selectedStores = options.retailers.join(",");
  const searchKey = `${options.currency}:${selectedStores}:${term}`;
  const suggestions = (search?.key === searchKey ? search.items : []).filter((offer) => options.retailers.includes(offer.retailer));

  useEffect(() => {
    storeGroceryDraft(account, { items, options });
  }, [account, items, options]);

  useEffect(() => {
    if (term.length < 2) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      api.get(`${endpoint}catalog/`, { params: { q: term, currency: options.currency, retailers: selectedStores }, signal: controller.signal })
        .then(({ data }) => { if (!controller.signal.aborted) setSearch({ key: searchKey, items: data }); })
        .catch(() => { if (!controller.signal.aborted) setSearch({ key: searchKey, items: [], failed: true }); });
    }, 240);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [options.currency, searchKey, selectedStores, term]);

  useEffect(() => {
    const controller = new AbortController();
    api.get(`${endpoint}lists/`, { signal: controller.signal })
      .then(({ data }) => { if (!controller.signal.aborted) setSaved(data); })
      .catch(() => { if (!controller.signal.aborted) setSavedError("Couldn’t load saved lists."); });
    api.get(`${endpoint}lists/invitations/`, { signal: controller.signal })
      .then(({ data }) => { if (!controller.signal.aborted) { setInvitations(data); setInvitationError(false); } })
      .catch(() => { if (!controller.signal.aborted) setInvitationError(true); });
    return () => controller.abort();
  }, [savedRevision]);

  function changeList(next) {
    setItems(next);
    setResult(null);
    setError("");
  }

  function changeOptions(next) {
    setOptions(next);
    setActive(-1);
    setResult(null);
    setError("");
  }

  function addItem(offer) {
    if ((!offer && !term) || items.length >= 40) return;
    const item = offer ? {
      ...defaultItem, offer_id: offer.id, name: offer.name, quantity: offer.quantity, unit: offer.unit,
      preferred_brand: offer.brand || "", image_url: offer.image_url,
    } : { ...defaultItem, name: term };
    changeList([...items, { ...item, id: ++id.current }]);
    setQuery("");
    setActive(-1);
    setDropdown(false);
    searchInput.current?.focus();
  }

  function editItem(key, patch) {
    changeList(items.map((item) => item.id === key ? { ...item, ...patch } : item));
  }

  function adjust(item, direction) {
    const step = item.unit === "kg" || item.unit === "l" ? 0.25 : item.unit === "ml" || item.unit === "g" ? 100 : 1;
    const base = Number(item.quantity);
    const minimum = base > 0 ? Math.min(base, step) : step;
    const value = Math.max(minimum, (Number.isFinite(base) ? base : 0) + step * direction);
    editItem(item.id, { quantity: String(value) });
  }

  function checkList() {
    if (!items.length || items.some((item) => !item.name.trim() || !Number.isFinite(Number(item.quantity)) || Number(item.quantity) <= 0)) {
      setError("Add at least one item and enter a positive quantity for every row.");
      return false;
    }
    return true;
  }

  async function optimize() {
    if (busy || !checkList()) return;
    setBusy("optimize");
    setError("");
    setNotice("");
    setResult(null);
    try {
      const { data } = await api.post(`${endpoint}optimize/`, basketSettings(items, options));
      setResult(data);
      setNotice(data.best_basket ? "Basket comparison ready." : "Comparison ready with unmatched items.");
      requestAnimationFrame(() => resultsHeading.current?.focus());
    } catch (failure) {
      setError(errorText(failure, "Couldn’t compare these offers. Try again."));
    } finally {
      setBusy("");
    }
  }

  async function save(event) {
    event.preventDefault();
    if (busy || !name.trim() || !checkList()) return;
    setBusy("save");
    setError("");
    try {
      await api.post(`${endpoint}lists/`, { name: name.trim(), ...basketSettings(items, options) });
      setNotice(`Saved ${name.trim()}.`);
      setName("");
      setSavedError("");
      setSavedRevision((value) => value + 1);
    } catch (failure) {
      setError(errorText(failure, "Couldn’t save this list."));
    } finally {
      setBusy("");
    }
  }

  async function household(url, body, openId) {
    setBusy("household");
    setSavedError("");
    try {
      const { data } = await api.post(url, body);
      if (openId === null) setSavedRevision((value) => value + 1);
      else navigate(`/grocery/household/${openId ?? data.id}`);
    } catch (failure) {
      setSavedError(errorText(failure, "Could not update the shared list."));
    } finally {
      setBusy("");
    }
  }

  function load(record) {
    const { items: rows, ...settings } = record.settings;
    changeList(rows.map((row) => ({ ...defaultItem, ...row, id: ++id.current })));
    changeOptions(settings);
    setNotice(`Loaded ${record.name}.`);
  }

  async function remove(record) {
    setBusy("delete");
    setSavedError("");
    try {
      await api.delete(`${endpoint}lists/${record.id}/`);
      setSaved((previous) => previous.filter((item) => item.id !== record.id));
      setNotice(`Deleted ${record.name}.`);
    } catch {
      setSavedError("Couldn’t delete this list.");
    } finally {
      setBusy("");
    }
  }

  const expanded = dropdown && term.length >= 2;
  return <main className="grocery-page">
    <header className="grocery-hero">
      <div className="grocery-hero-icon"><FiShoppingCart aria-hidden="true" /></div>
      <div><h1>Grocery basket optimizer</h1>
        <p>Build your list and compare the cost of buying whole packs across retailers.</p>
        <Link className="dash-link" to="/my-deals">My Deals</Link></div>
      <div className="grocery-hero-stores">{retailerIds.map((id) => <RetailerMark key={id} id={id} />)}</div>
    </header>

    <div className="grocery-builder-layout">
      <section className="grocery-panel" aria-labelledby="grocery-list-heading">
        <div className="grocery-section-heading"><h2 id="grocery-list-heading">Your shopping list</h2><span className="grocery-muted">{items.length} / 40 items</span></div>
        <form className="grocery-search" onSubmit={(event) => {
          event.preventDefault();
          addItem(expanded && active >= 0 ? suggestions[active] : undefined);
        }}>
          <label htmlFor="grocery-search-input">Find a product</label>
          <div className="grocery-search-row">
            <span className="grocery-search-field"><FiSearch aria-hidden="true" />
              <input id="grocery-search-input" ref={searchInput} role="combobox" aria-autocomplete="list"
                aria-controls="grocery-suggestions" aria-expanded={expanded} autoComplete="off"
                aria-activedescendant={expanded && suggestions[active] ? `grocery-option-${suggestions[active].id}` : undefined}
                placeholder="Search milk, eggs, rice…" value={query} maxLength={100} disabled={Boolean(busy)}
                onFocus={() => setDropdown(true)} onBlur={() => setDropdown(false)}
                onChange={(event) => { setQuery(event.target.value); setDropdown(true); setActive(-1); }}
                onKeyDown={(event) => {
                  if (event.key === "Escape") { setDropdown(false); setActive(-1); }
                  if (!suggestions.length || !["ArrowDown", "ArrowUp"].includes(event.key)) return;
                  event.preventDefault();
                  setDropdown(true);
                  setActive((index) => event.key === "ArrowDown"
                    ? (index + 1) % suggestions.length : (index <= 0 ? suggestions.length - 1 : index - 1));
                }} />
            </span>
            <button type="submit" disabled={!term || items.length >= 40 || Boolean(busy)}><FiPlus aria-hidden="true" /> Add item</button>
          </div>
          <div className="grocery-suggestions" hidden={!expanded}>
            <ul id="grocery-suggestions" role="listbox" aria-label="Catalog suggestions">
              {suggestions.map((offer, index) => <li id={`grocery-option-${offer.id}`} key={offer.id} role="option"
                aria-selected={index === active} onMouseDown={(event) => event.preventDefault()} onClick={() => addItem(offer)}>
                <ProductImage key={offer.image_url} src={offer.image_url} />
                <span><strong>{offer.name}</strong><small>{offer.quantity} {units[offer.unit]} · <RetailerMark id={offer.retailer} /></small></span>
                <strong>{money(offer.price, offer.currency)}</strong>
              </li>)}
            </ul>
            {!suggestions.length && <p role="status">{search?.key !== searchKey ? "Searching advertised offers…"
              : search.failed ? "Catalog search is unavailable. You can still add a product by name."
                : "No current catalog matches. Press Enter to add this name to your list."}</p>}
          </div>
        </form>
        {!items.length ? <div className="grocery-empty"><FiShoppingCart aria-hidden="true" />
          <h3>Start with an item you need</h3><p className="grocery-muted">Search the catalog or enter a product name, then choose how much you need.</p></div>
          : <div className="grocery-edit-list">{items.map((item, index) => <fieldset className="grocery-edit-item" key={item.id} disabled={Boolean(busy)}>
            <legend>Item {index + 1}</legend>
            <div className="grocery-edit-main">
              <ProductImage key={item.image_url} src={item.image_url} />
              <label>Product<input value={item.name} maxLength={180}
                onChange={(event) => editItem(item.id, { name: event.target.value, image_url: "", offer_id: null })} /></label>
              <button type="button" aria-label={`Remove item ${index + 1}`} onClick={() => changeList(items.filter((row) => row.id !== item.id))}><FiTrash2 aria-hidden="true" /></button>
            </div>
            <div className="grocery-edit-fields">
              <label htmlFor={`grocery-qty-${item.id}`}>Quantity
                <span className="grocery-stepper">
                  <button type="button" aria-label={`Decrease quantity for item ${index + 1}`} onClick={() => adjust(item, -1)}><FiMinus aria-hidden="true" /></button>
                  <input id={`grocery-qty-${item.id}`} inputMode="decimal" value={item.quantity}
                    onChange={(event) => editItem(item.id, { quantity: event.target.value.replace(",", ".") })} />
                  <button type="button" aria-label={`Increase quantity for item ${index + 1}`} onClick={() => adjust(item, 1)}><FiPlus aria-hidden="true" /></button>
                </span>
              </label>
              <label>Unit<select value={item.unit} onChange={(event) => editItem(item.id, { unit: event.target.value })}>
                <option value="">Auto</option>{Object.entries(units).map(([value, label]) => <option value={value} key={value}>{label}</option>)}
              </select></label>
              <label>Preferred brand<input value={item.preferred_brand} maxLength={120}
                onChange={(event) => editItem(item.id, { preferred_brand: event.target.value })} placeholder="Any brand" /></label>
            </div>
            <label className="grocery-check-label"><input type="checkbox" checked={item.allow_substitutions}
              onChange={(event) => editItem(item.id, { allow_substitutions: event.target.checked })} /> Allow substitutions</label>
          </fieldset>)}</div>}
      </section>

      <aside className="grocery-sidebar">
        <section className="grocery-panel" aria-labelledby="grocery-options-heading">
          <h2 id="grocery-options-heading">Comparison settings</h2>
          <fieldset className="grocery-retailer-options" disabled={Boolean(busy)}><legend>Include retailers</legend>
            {retailerIds.map((store) => <label key={store}>
              <input type="checkbox" checked={options.retailers.includes(store)} disabled={options.retailers.length === 1 && options.retailers.includes(store)}
                onChange={(event) => {
                  const retailers = event.target.checked ? [...options.retailers, store] : options.retailers.filter((key) => key !== store);
                  changeOptions({ ...options, retailers, max_stores: Math.min(retailers.length, options.max_stores) });
                }} /> <RetailerMark id={store} />
            </label>)}
          </fieldset>
          <label className="grocery-check-label"><input type="checkbox" checked={options.allow_multi_store}
            disabled={Boolean(busy)} onChange={(event) => changeOptions({ ...options, allow_multi_store: event.target.checked })} /> Compare multi-store options</label>
          <div className="grocery-setting-grid">
            <label>Maximum stores<select value={options.max_stores} disabled={!options.allow_multi_store || Boolean(busy)}
              onChange={(event) => changeOptions({ ...options, max_stores: Number(event.target.value) })}>
              {Array.from({ length: options.retailers.length }, (_, index) => <option key={index} value={index + 1}>{index + 1}</option>)}
            </select></label>
            <label>Currency<select value={options.currency} disabled={Boolean(busy)} onChange={(event) => changeOptions({ ...options, currency: event.target.value })}>
              <option>EUR</option><option>BGN</option>
            </select></label>
            <label>Overhead per store<input inputMode="decimal" value={options.overhead_per_store} disabled={Boolean(busy)}
              onChange={(event) => changeOptions({ ...options, overhead_per_store: event.target.value.replace(",", ".") })} /></label>
          </div>
          <button className="grocery-primary" type="button" disabled={Boolean(busy) || !items.length} onClick={optimize}>
            {busy === "optimize" ? "Comparing offers…" : "Optimize basket"} <FiArrowRight aria-hidden="true" />
          </button>
          <p className="grocery-muted">Based on advertised offers. Store inventory is unverified.</p>
        </section>

        <section className="grocery-panel" aria-labelledby="grocery-saved-heading">
          <h2 id="grocery-saved-heading">Saved lists</h2>
          <form onSubmit={save}><label>List name<input value={name} maxLength={80} disabled={Boolean(busy)}
            onChange={(event) => setName(event.target.value)} /></label>
            <button type="submit" disabled={Boolean(busy) || !items.length || !name.trim()}>Save list</button>
            <button type="button" disabled={Boolean(busy) || !name.trim()} onClick={() => household(`${endpoint}lists/`, {
              name: name.trim(), shared: true, ...basketSettings(items, options),
            })}>Create shared list</button></form>
          {invitationError && <p role="alert">Could not load invitations. <button type="button"
            onClick={() => setSavedRevision((value) => value + 1)}>Retry invitations</button></p>}
          {invitations.length > 0 && <ul className="grocery-saved-list" aria-label="Shopping list invitations">
            {invitations.map((invitation) => <li key={invitation.list_id}>
              <span>{invitation.invited_by} invited you to {invitation.name}</span>
              <button type="button" disabled={Boolean(busy)} onClick={() => household(
                `${endpoint}lists/${invitation.list_id}/invitation/`, { accept: true }, invitation.list_id,
              )}>Accept invitation</button>
              <button type="button" disabled={Boolean(busy)} onClick={() => household(
                `${endpoint}lists/${invitation.list_id}/invitation/`, { accept: false }, null,
              )}>Decline</button>
            </li>)}</ul>}
          {savedError ? <p role="alert">{savedError} <button type="button" onClick={() => { setSavedError(""); setSavedRevision((value) => value + 1); }}>Try again</button></p>
            : saved === null ? <p className="grocery-muted" role="status">Loading saved lists…</p>
              : !saved.length ? <p className="grocery-muted">Save a named list to use it again.</p>
                : <ul className="grocery-saved-list">{saved.map((record) => <li key={record.id}>
                  <strong>{record.name}</strong>
                  <span>{record.shared
                    ? <Link className="dash-link" to={`/grocery/household/${record.id}`}>Open shared list</Link>
                    : <>
                      <button type="button" onClick={() => load(record)} disabled={Boolean(busy)} aria-label={`Load ${record.name}`}>Load</button>
                      <button type="button" disabled={Boolean(busy)} onClick={() => household(
                        `${endpoint}lists/${record.id}/household/`, {}, record.id,
                      )}>Enable sharing</button>
                    </>}
                    {record.can_manage && <button type="button" onClick={() => remove(record)} disabled={Boolean(busy)} aria-label={`Delete ${record.name}`}><FiTrash2 aria-hidden="true" /></button>}</span>
                </li>)}</ul>}
        </section>
      </aside>
    </div>

    {error && <p role="alert" className="grocery-warning">{error}</p>}
    <p role="status" className="grocery-status">{busy === "optimize" ? "Calculating whole-package costs…" : notice}</p>
    {result ? <div ref={resultsHeading} tabIndex={-1}><GroceryBasketResults result={result} /></div>
      : !busy && <div className="grocery-panel grocery-results-empty"><h2>Basket comparison</h2><p className="grocery-muted">Optimize your list to see retailer totals, estimated savings, and a shopping checklist.</p></div>}
  </main>;
}
