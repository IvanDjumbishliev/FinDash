import { useEffect, useRef, useState } from "react";
import PropTypes from "prop-types";
import { Link, useParams } from "react-router-dom";
import api from "../api";
import GroceryBasketResults from "../components/GroceryBasketResults";
import { DashboardLoading } from "../components/DashboardFeedback";
import { units } from "../groceryOptimizer";
import { receiptApiError } from "../receiptScanner";
import "../styles/pages/GroceryOptimizer.css";
import "../styles/pages/HouseholdGroceries.css";

const blank = { name: "", quantity: "1", unit: "item" };

function SharedItem({ item, busy, change, remove }) {
  const [draft, setDraft] = useState(null);
  return <li className="household-item">
    <div><strong>{item.product.name}</strong>
      <small>Added by {item.added_by ?? "Former user"}
        {item.purchased && ` · Purchased by ${item.completed_by ?? "Former user"}`}</small></div>
    <form onSubmit={async (event) => {
      event.preventDefault();
      if (draft) await change({ quantity: draft.quantity, revision: draft.revision });
      setDraft(null);
    }}>
      <input type="number" min="0.000001" step="any" required
        aria-label={`Quantity for ${item.product.name}`} value={draft?.quantity ?? item.product.quantity} disabled={busy}
        onChange={(event) => setDraft({ quantity: event.target.value, revision: draft?.revision ?? item.revision })} />
      <span>{units[item.product.unit]}</span>
      <button type="submit" disabled={busy || !draft}>Save quantity</button>
    </form>
    <div className="dash-actions">
      <button type="button" disabled={busy} onClick={() => change({ purchased: !item.purchased, revision: item.revision })}>
        {item.purchased ? "Mark unpurchased" : "Mark purchased"}</button>
      <button type="button" disabled={busy} onClick={remove}>Remove item</button>
    </div>
  </li>;
}

SharedItem.propTypes = { item: PropTypes.shape({
  revision: PropTypes.number.isRequired, added_by: PropTypes.string, completed_by: PropTypes.string,
  purchased: PropTypes.bool.isRequired,
  product: PropTypes.shape({ name: PropTypes.string.isRequired, quantity: PropTypes.string.isRequired,
    unit: PropTypes.string.isRequired }).isRequired,
}).isRequired, busy: PropTypes.bool.isRequired, change: PropTypes.func.isRequired, remove: PropTypes.func.isRequired };

export default function HouseholdGroceries() {
  const { id } = useParams();
  return <HouseholdList key={id} id={id} />;
}

function HouseholdList({ id }) {
  const validId = /^[1-9]\d{0,18}$/.test(id || "");
  const path = `/api/grocery/lists/${id}/`;
  const [record, setRecord] = useState(null);
  const [error, setError] = useState("");
  const [denied, setDenied] = useState(false);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [entry, setEntry] = useState(blank);
  const [username, setUsername] = useState("");
  const [comparison, setComparison] = useState(null);
  const mutation = useRef(null);

  const snapshot = record?.items.map(({ id, revision }) => `${id}:${revision}`).join(",");
  function unavailable() {
    setRecord(null);
    setComparison(null);
    setDenied(true);
    setError("This shared list is unavailable or your access was removed.");
  }

  useEffect(() => () => mutation.current?.abort(), []);
  useEffect(() => {
    if (denied || !validId) return;
    const controller = new AbortController();
    let timer;
    async function poll() {
      if (!document.hidden) {
        try {
          const { data } = await api.get(`${path}household/`, { signal: controller.signal, timeout: 10000 });
          if (!controller.signal.aborted) setRecord(data);
        } catch (failure) {
          if (controller.signal.aborted) return;
          if ([401, 403, 404].includes(failure.response?.status)) { unavailable(); return; }
          setError("Could not refresh the list. Try again.");
        }
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, 8000);
    }
    poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [denied, path, revision, validId]);

  async function act(method, subpath, data, params) {
    if (mutation.current || denied) return null;
    const controller = new AbortController();
    mutation.current = controller;
    setBusy(true);
    setError("");
    try {
      const response = await api.request({ url: path + subpath, method, data, params,
        signal: controller.signal, timeout: 15000 });
      if (controller.signal.aborted) return null;
      setRevision((value) => value + 1);
      return response;
    } catch (failure) {
      if (!controller.signal.aborted) {
        if ([401, 403].includes(failure.response?.status)) unavailable();
        else {
          setError(receiptApiError(failure, "Could not update the list."));
          setRevision((value) => value + 1);
        }
      }
      return null;
    } finally {
      mutation.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return <main className="grocery-page household-page">
    <header className="grocery-hero"><div><h1>{record?.name || "Shared shopping list"}</h1>
      <p>Work on this list with accepted household members.</p>
      <Link className="dash-link" to="/grocery">Back to saved lists</Link></div></header>
    {error && <p role="alert" className="grocery-warning">{error}
      {!denied && <button type="button" onClick={() => { setError(""); setRevision((value) => value + 1); }}>Reload list</button>}</p>}
    {!validId && <p role="alert">This shared list is unavailable.</p>}
    {!record && !error && validId && <DashboardLoading label="Loading shared list" />}
    {record && <>
      <div className="grocery-builder-layout">
        <section className="grocery-panel">
          <h2>Shopping items</h2>
          <form className="household-add" onSubmit={async (event) => {
            event.preventDefault();
            if (await act("post", "items/", entry)) setEntry(blank);
          }}>
            <label>Product <input required maxLength={180} value={entry.name}
              onChange={(event) => setEntry({ ...entry, name: event.target.value })} /></label>
            <label>Quantity <input required type="number" min="0.000001" step="any" value={entry.quantity}
              onChange={(event) => setEntry({ ...entry, quantity: event.target.value })} /></label>
            <label>Unit <select value={entry.unit} onChange={(event) => setEntry({ ...entry, unit: event.target.value })}>
              {Object.entries(units).map(([unit, label]) => <option key={unit} value={unit}>{label}</option>)}</select></label>
            <button type="submit" disabled={busy}>Add product</button>
          </form>
          {record.items.length ? <ul className="household-items">{record.items.map((item) => <SharedItem key={item.id}
            item={item} busy={busy} change={(data) => act("patch", `items/${item.id}/`, data)}
            remove={() => act("delete", `items/${item.id}/`, undefined, { revision: item.revision })} />)}</ul>
            : <p className="grocery-muted">The list is empty. Add a product to start.</p>}
          <button type="button" className="grocery-primary" disabled={busy || !record.items.some((item) => !item.purchased)}
            onClick={async () => {
              const response = await act("post", "optimize/");
              if (response) setComparison({ snapshot, result: response.data });
            }}>Optimize unpurchased items</button>
        </section>
        {record.can_manage && <section className="grocery-panel">
          <h2>Household members</h2>
          <form className="household-invite" onSubmit={async (event) => {
            event.preventDefault();
            if (await act("post", "members/", { username: username.trim() })) setUsername("");
          }}>
            <label>FinDash username <input required value={username} maxLength={150}
              onChange={(event) => setUsername(event.target.value)} /></label>
            <button type="submit" disabled={busy}>Invite user</button>
          </form>
          <p className="grocery-muted">Invited users can see the shopping list after they accept.</p>
          <ul className="household-members">{record.members.map((member) => <li key={member.id}>
            <span>{member.username} · {member.accepted ? "Member" : "Invited"}</span>
            <button type="button" disabled={busy} onClick={() => act("delete", `members/${member.id}/`)}>Remove {member.username}</button>
          </li>)}</ul>
        </section>}
      </div>
      {comparison?.snapshot === snapshot && <GroceryBasketResults result={comparison.result} />}
      {comparison && comparison.snapshot !== snapshot && <p role="status">The list changed. Optimize again for current results.</p>}
    </>}
  </main>;
}

HouseholdList.propTypes = { id: PropTypes.string };
