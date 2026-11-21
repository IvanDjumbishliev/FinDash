import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import PropTypes from "prop-types";
import api from "../api";
import { orderId, responseError } from "../virtualPortfolio";

export default function VirtualTradeDialog({ portfolio, initial, stocks, onClose, onRecorded }) {
  const [draft, setDraft] = useState({ side: initial.side, ticker: initial.ticker, quantity: "", price: "", fees: "0" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const dialog = useRef(null);
  const retryId = useRef(null);

  useEffect(() => {
    const node = dialog.current;
    node.showModal();
    return () => node.close();
  }, []);

  function set(key, value) {
    setDraft((previous) => ({ ...previous, [key]: value }));
    retryId.current = null;
    setError("");
  }

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      retryId.current ??= orderId();
      await api.post(`/api/portfolios/${portfolio.id}/trades/`, {
        ...draft, ticker: draft.ticker.trim().toUpperCase(),
        quantity: draft.quantity.replace(",", "."), price: draft.price.replace(",", "."),
        fees: draft.fees.replace(",", ".") || "0", currency: portfolio.currency,
        client_order_id: retryId.current,
      });
      onRecorded();
    } catch (failure) {
      setError(responseError(failure, "The simulated trade could not be recorded. You can retry these terms."));
    } finally {
      setBusy(false);
    }
  }

  return <dialog ref={dialog} className="portfolio-dialog" aria-labelledby="portfolio-dialog-heading"
    onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}>
    <h2 id="portfolio-dialog-heading">Simulate a trade</h2>
    <p className="portfolio-muted">{portfolio.name} · {portfolio.currency}</p>
    <form onSubmit={submit}>
      <fieldset disabled={busy}>
        <label>Simulated action<select value={draft.side} onChange={(event) => set("side", event.target.value)}>
          <option value="buy">Simulated buy</option><option value="sell">Simulated sell</option>
        </select></label>
        <label>Ticker<input list="portfolio-watchlist" required maxLength={10} value={draft.ticker}
          onChange={(event) => set("ticker", event.target.value)} /></label>
        <datalist id="portfolio-watchlist">{stocks.map((stock) => <option key={stock.symbol} value={stock.symbol}>{stock.name}</option>)}</datalist>
        <label>Quantity<input required inputMode="decimal" value={draft.quantity}
          onChange={(event) => set("quantity", event.target.value)} /></label>
        <label>Simulated price per share ({portfolio.currency})<input required inputMode="decimal" value={draft.price}
          onChange={(event) => set("price", event.target.value)} /></label>
        <label>Simulated fees ({portfolio.currency})<input inputMode="decimal" value={draft.fees}
          onChange={(event) => set("fees", event.target.value)} /></label>
      </fieldset>
      <p className="portfolio-muted">Enter your own simulated execution price. Market quotes are shown separately.</p>
      {error && <p className="portfolio-alert" role="alert">{error}</p>}
      <div className="portfolio-actions">
        <button className="portfolio-primary" type="submit" disabled={busy}>{busy ? "Recording…" : "Record simulated trade"}</button>
        <button type="button" disabled={busy} onClick={onClose}>Cancel</button>
        <Link to="/stocks">Stock watchlist</Link>
      </div>
    </form>
  </dialog>;
}

VirtualTradeDialog.propTypes = {
  portfolio: PropTypes.shape({ id: PropTypes.number, name: PropTypes.string, currency: PropTypes.string }).isRequired,
  initial: PropTypes.shape({ side: PropTypes.string, ticker: PropTypes.string }).isRequired,
  stocks: PropTypes.arrayOf(PropTypes.shape({ symbol: PropTypes.string, name: PropTypes.string })).isRequired,
  onClose: PropTypes.func.isRequired, onRecorded: PropTypes.func.isRequired,
};
