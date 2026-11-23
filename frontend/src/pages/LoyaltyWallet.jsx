import { useEffect, useRef, useState } from "react";
import PropTypes from "prop-types";
import { FiCreditCard, FiStar } from "react-icons/fi";
import toast from "react-hot-toast";
import api from "../api";
import { DashboardError, DashboardLoading } from "../components/DashboardFeedback";
import LoyaltyDisplay from "../components/loyalty/LoyaltyDisplay";
import { receiptApiError } from "../receiptScanner";
import "../styles/pages/LoyaltyWallet.css";

const endpoint = "/api/loyalty-cards/";
const formats = { none: "Identifier only", code128: "Code 128", ean13: "EAN-13", ean8: "EAN-8", upca: "UPC-A", qrcode: "QR code" };
const newCard = { retailer: "", label: "", identifier: "", code_format: "none", favorite: false };

function CardEditor({ initial, busy, error, onCancel, onSave }) {
  const [fields, setFields] = useState(() => Object.fromEntries(
    Object.keys(newCard).map((name) => [name, initial[name]]),
  ));
  const [confirmed, setConfirmed] = useState(false);
  const name = useRef(null);
  useEffect(() => { name.current?.focus(); }, []);
  const verify = fields.code_format !== "none" &&
    (fields.code_format !== initial.code_format || fields.identifier !== initial.identifier);

  function update(key, value) {
    setFields((previous) => ({ ...previous, [key]: value }));
    if (key === "code_format" || key === "identifier") setConfirmed(false);
  }

  return <section className="dash-panel loyalty-panel" aria-labelledby="loyalty-editor-title">
    <h2 id="loyalty-editor-title">{initial.id ? "Edit loyalty card" : "Add loyalty card"}</h2>
    <form onSubmit={(event) => {
      event.preventDefault();
      if (!verify || confirmed) onSave({ ...fields, original_format_confirmed: confirmed });
    }}>
      <fieldset disabled={busy}>
        <div className="loyalty-fields">
          <label>Retailer<input ref={name} value={fields.retailer} required maxLength={120}
            onChange={(event) => update("retailer", event.target.value)} /></label>
          <label>Label <small>Optional</small><input value={fields.label} maxLength={80}
            onChange={(event) => update("label", event.target.value)} /></label>
          <label>Membership identifier<input value={fields.identifier} required maxLength={64} autoComplete="off"
            autoCapitalize="off" spellCheck={false} onChange={(event) => update("identifier", event.target.value)} /></label>
          <label>Original card format<select value={fields.code_format} onChange={(event) => update("code_format", event.target.value)}>
            {Object.entries(formats).map(([value, text]) => <option key={value} value={value}>{text}</option>)}
          </select></label>
        </div>
        <p className="loyalty-muted">If the format or encoded value is unknown, choose Identifier only. Enter loyalty information only.</p>
        {verify && <label className="loyalty-check"><input type="checkbox" required checked={confirmed}
          onChange={(event) => setConfirmed(event.target.checked)} /> This is the original format and exact value encoded by the card.</label>}
        <label className="loyalty-check"><input type="checkbox" checked={fields.favorite}
          onChange={(event) => update("favorite", event.target.checked)} /> Favorite</label>
        {error && <p role="alert" className="loyalty-note">{error}</p>}
        <div className="dash-actions">
          <button className="dash-button dash-primary" type="submit" disabled={verify && !confirmed}>Save card</button>
          <button className="dash-button" type="button" onClick={onCancel}>Cancel</button>
        </div>
      </fieldset>
    </form>
  </section>;
}

CardEditor.propTypes = {
  initial: PropTypes.object.isRequired, busy: PropTypes.bool.isRequired, error: PropTypes.string.isRequired,
  onCancel: PropTypes.func.isRequired, onSave: PropTypes.func.isRequired,
};

export default function LoyaltyWallet() {
  const [list, setList] = useState(null);
  const [revision, setRevision] = useState(0);
  const [query, setQuery] = useState("");
  const [favorites, setFavorites] = useState(false);
  const [editor, setEditor] = useState(null);
  const [active, setActive] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = useRef(null);

  const refresh = () => setRevision((value) => value + 1);
  useEffect(() => () => pending.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController();
    api.get(endpoint, { signal: controller.signal, timeout: 12000 })
      .then(({ data }) => { if (!controller.signal.aborted) setList({ data }); })
      .catch(() => { if (!controller.signal.aborted) setList({ failed: true }); });
    return () => controller.abort();
  }, [revision]);

  async function act(work, success) {
    if (pending.current) return;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);
    setError("");
    try {
      await work({ signal: controller.signal, timeout: 12000 });
      if (controller.signal.aborted) return;
      if (success) { refresh(); toast.success(success); }
    } catch (failure) {
      if (!controller.signal.aborted) setError(receiptApiError(failure, "Could not update the wallet. Try again."));
    } finally {
      pending.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  const term = query.trim().normalize("NFKC").toLowerCase();
  const cards = list?.data?.filter((card) => (!favorites || card.favorite)
    && [card.retailer, card.label].some((text) => text.normalize("NFKC").toLowerCase().includes(term))) || [];

  return <main className="dashboard-shell loyalty-wallet">
    <header className="market-heading">
      <h1><FiCreditCard aria-hidden="true" /> Loyalty Card Wallet</h1>
      <p>Keep your membership cards together and show the original code at checkout.</p>
      <button className="dash-button dash-primary" type="button" disabled={busy}
        onClick={() => { setError(""); setEditor(newCard); }}>Add loyalty card</button>
    </header>
    {error && !editor && <p role="alert" className="loyalty-note">{error}</p>}
    {editor && <CardEditor key={editor.id || "new"} initial={editor} busy={busy} error={error}
      onCancel={() => { setEditor(null); setError(""); }} onSave={(data) => act(async (options) => {
        if (editor.id) await api.patch(`${endpoint}${editor.id}/`, data, options);
        else await api.post(endpoint, data, options);
        if (!options.signal.aborted) setEditor(null);
      }, "Loyalty card saved")} />}
    <section className="dash-panel loyalty-panel" aria-labelledby="loyalty-list-title">
      <h2 id="loyalty-list-title">Your cards</h2>
      <div className="loyalty-search">
        <label>Search retailers or labels<input type="search" maxLength={120} value={query}
          onChange={(event) => setQuery(event.target.value)} /></label>
        <button className="dash-button" type="button" aria-pressed={favorites}
          onClick={() => setFavorites(!favorites)}><FiStar aria-hidden="true" /> Favorites only</button>
      </div>
      {!list ? <DashboardLoading label="Loading loyalty cards" />
        : list.failed ? <DashboardError onRetry={refresh}>Could not load your loyalty cards.</DashboardError>
          : !cards.length ? <p role="status">{list.data.length ? "No cards match these filters." : "Add a loyalty card to get started."}</p>
            : <div className="loyalty-grid">
              {cards.map((card) => <article key={card.id}>
                <div className="loyalty-card-title">
                  <div><h3>{card.retailer}</h3>{card.label && <p className="loyalty-muted">{card.label}</p>}</div>
                  <button className="dash-button" type="button" aria-label={`Favorite ${card.retailer}`}
                    aria-pressed={card.favorite} disabled={busy} onClick={() => act((options) => api.patch(
                      `${endpoint}${card.id}/`, { favorite: !card.favorite }, options,
                    ), card.favorite ? "Removed from favorites" : "Added to favorites")}><FiStar aria-hidden="true" /></button>
                </div>
                <p className="loyalty-muted">{formats[card.code_format]}{card.has_image && " · Image attached"}</p>
                <div className="dash-actions">
                  <button className="dash-button dash-primary" type="button" disabled={busy}
                    onClick={() => act(async (options) => {
                      const { data } = await api.get(`${endpoint}${card.id}/`, options);
                      if (!options.signal.aborted) { setEditor(null); setActive(data); }
                    })}>Show card<span className="loyalty-sr"> {card.retailer}</span></button>
                  {deleting === card.id ? <>
                    <button className="dash-button" type="button" disabled={busy} onClick={() => act(async (options) => {
                      await api.delete(`${endpoint}${card.id}/`, options);
                      if (!options.signal.aborted) {
                        if (editor?.id === card.id) setEditor(null);
                        setDeleting(null);
                      }
                    }, "Loyalty card deleted")}>Confirm delete</button>
                    <button className="dash-button" type="button" disabled={busy} onClick={() => setDeleting(null)}>Keep card</button>
                  </> : <button className="dash-button" type="button" disabled={busy} onClick={() => setDeleting(card.id)}>
                    Delete card<span className="loyalty-sr"> {card.retailer}</span>
                  </button>}
                </div>
              </article>)}
            </div>}
    </section>
    {active && <LoyaltyDisplay key={active.id} card={active} onClose={() => setActive(null)}
      onEdit={() => { setEditor(active); setActive(null); }}
      onImageChanged={(has_image) => { setActive((previous) => ({ ...previous, has_image })); refresh(); }} />}
  </main>;
}
