import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { FiActivity, FiPlus, FiRefreshCw } from "react-icons/fi";
import api from "../api";
import PortfolioCharts from "../components/PortfolioCharts";
import VirtualTradeDialog from "../components/VirtualTradeDialog";
import { money } from "../copilotPresentation";
import { formatTimestamp, marketFreshness, quoteStatus, responseError } from "../virtualPortfolio";
import "../styles/pages/PortfolioSimulator.css";

const endpoint = "/api/portfolios/";
const pageSize = 15;
const quantity = new Intl.NumberFormat(undefined, { maximumFractionDigits: 8 });
const precision = new Intl.NumberFormat(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 8 });
const tradeMoney = (amount, currency) => `${currency} ${precision.format(Number(amount))}`;

export default function PortfolioSimulator() {
  const [search, setSearch] = useSearchParams();
  const [dialog, setDialog] = useState(() => search.get("ticker") ? { side: "buy", ticker: search.get("ticker").slice(0, 10) } : null);
  const [portfolios, setPortfolios] = useState(null);
  const [selected, setSelected] = useState(null);
  const [listError, setListError] = useState("");
  const [listRetry, setListRetry] = useState(0);
  const [revision, setRevision] = useState(0);
  const [snapshot, setSnapshot] = useState(null);
  const [history, setHistory] = useState(null);
  const [more, setMore] = useState("");
  const [stocks, setStocks] = useState([]);
  const [watchlistError, setWatchlistError] = useState(false);
  const [name, setName] = useState("");
  const [newCurrency, setNewCurrency] = useState("USD");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");
  const [message, setMessage] = useState("");
  const portfolio = portfolios?.find((row) => row.id === selected) ?? portfolios?.[0];
  const id = portfolio?.id;
  const path = id ? `${endpoint}${id}/` : "";
  const key = `${id}:${revision}`;
  const report = snapshot?.key === key ? snapshot : null;
  const tradeHistory = history?.key === key ? history : null;

  useEffect(() => {
    const controller = new AbortController();
    api.get(endpoint, { signal: controller.signal }).then(({ data }) => {
      if (!controller.signal.aborted) setPortfolios(data);
    }).catch(() => {
      if (!controller.signal.aborted) setListError("Couldn’t load virtual portfolios.");
    });
    return () => controller.abort();
  }, [listRetry]);

  useEffect(() => {
    const controller = new AbortController();
    api.get("/api/stocks/watchlist/", { params: { include_history: false }, signal: controller.signal }).then(({ data }) => {
      if (!controller.signal.aborted) setStocks(data.stocks);
    }).catch(() => {
      if (!controller.signal.aborted) setWatchlistError(true);
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    const options = { signal: controller.signal };
    api.get(`${path}performance/`, options).then(({ data }) => {
      if (!controller.signal.aborted) setSnapshot({ key, data });
    }).catch((error) => {
      if (!controller.signal.aborted) setSnapshot({ key, error: responseError(error, "Couldn’t load the portfolio valuation.") });
    });
    api.get(`${path}trades/`, { ...options, params: { limit: pageSize } }).then(({ data }) => {
      if (!controller.signal.aborted) setHistory({ key, rows: data.results, next: data.next, offset: data.results.length });
    }).catch(() => {
      if (!controller.signal.aborted) setHistory({ key, error: "Couldn’t load simulated trade history." });
    });
    return () => controller.abort();
  }, [key, path]);

  async function createPortfolio(event) {
    event.preventDefault();
    if (!name.trim() || creating) return;
    setCreating(true);
    setCreateError("");
    try {
      const { data } = await api.post(endpoint, { name: name.trim(), currency: newCurrency });
      setPortfolios((previous) => [data, ...(previous ?? [])]);
      setSelected(data.id);
      setName("");
      setMessage("Virtual portfolio created.");
    } catch (error) {
      setCreateError(responseError(error, "Couldn’t create the virtual portfolio."));
    } finally {
      setCreating(false);
    }
  }

  function closeTrade() {
    setDialog(null);
    if (search.has("ticker")) setSearch({}, { replace: true });
  }

  async function moreTrades() {
    if (more === key || !tradeHistory?.next) return;
    setMore(key);
    try {
      const { data } = await api.get(`${path}trades/`, { params: { limit: pageSize, offset: tradeHistory.offset } });
      setHistory((previous) => previous?.key === key ? {
        key, rows: [...new Map([...previous.rows, ...data.results].map((trade) => [trade.id, trade])).values()],
        next: data.next, offset: previous.offset + data.results.length,
      } : previous);
    } catch {
      setHistory((previous) => previous?.key === key ? { ...previous, moreError: "Couldn’t load older trades." } : previous);
    } finally {
      setMore((previous) => previous === key ? "" : previous);
    }
  }

  const data = report?.data;
  const stats = data?.performance;
  const currency = portfolio?.currency ?? "USD";
  const value = (amount) => amount == null ? "Unavailable" : money(amount, currency);
  const freshness = data && marketFreshness(data);

  return <main className="portfolio-page">
    <header className="portfolio-hero">
      <div className="portfolio-icon"><FiActivity aria-hidden="true" /></div>
      <div><h1>Investment portfolio simulator</h1><p>Practice investment decisions with simulated trades and tracked positions.</p></div>
      <Link to="/stocks">Stock watchlist</Link>
    </header>

    {portfolios === null && !listError && <p role="status" className="portfolio-panel">Loading virtual portfolios…</p>}
    {listError && <p className="portfolio-alert" role="alert">{listError} <button type="button" onClick={() => {
      setListError("");
      setListRetry((previous) => previous + 1);
    }}>Try again</button></p>}
    {portfolios && <>
      <div className="portfolio-selector portfolio-panel">
        {portfolio ? <>
          <label>Virtual portfolio<select value={portfolio.id} onChange={(event) => { setSelected(Number(event.target.value)); setMessage(""); }}>
            {portfolios.map((row) => <option key={row.id} value={row.id}>{row.name} · {row.currency}</option>)}
          </select></label>
          <div className="portfolio-actions">
            <button className="portfolio-primary" type="button" onClick={() => setDialog({ side: "buy", ticker: "" })}>
              <FiPlus aria-hidden="true" /> Simulate trade</button>
            <button type="button" onClick={() => setRevision((previous) => previous + 1)}><FiRefreshCw aria-hidden="true" /> Refresh valuation</button>
          </div>
        </> : <div><h2>Create your first virtual portfolio</h2><p className="portfolio-muted">Choose a currency for simulated trades and position values.</p></div>}
        <details open={!portfolio || undefined}>
          <summary>New virtual portfolio</summary>
          <form className="portfolio-create" onSubmit={createPortfolio}>
            <label>Name<input required maxLength={100} value={name} disabled={creating} onChange={(event) => setName(event.target.value)} /></label>
            <label>Currency code<input required pattern="[A-Z]{3}" maxLength={3} value={newCurrency} disabled={creating}
              onChange={(event) => setNewCurrency(event.target.value.toUpperCase())} /></label>
            <button type="submit" disabled={creating || !name.trim()}>{creating ? "Creating…" : "Create portfolio"}</button>
          </form>
          {createError && <p role="alert" className="portfolio-alert">{createError}</p>}
        </details>
      </div>
      <p className="portfolio-status" role="status">{message}</p>
    </>}

    {portfolio && <>
      {!report && <p className="portfolio-panel" role="status">Loading valuation and holdings…</p>}
      {report?.error && <p className="portfolio-alert" role="alert">{report.error}</p>}
      {stats && <>
        <dl className="portfolio-kpis">
          <div><dt>Virtual portfolio balance</dt><dd>{value(stats.market_value)}</dd>
            <dd>Market value of open positions{stats.valuation_complete ? "" : `; priced subtotal ${value(stats.priced_market_value)}`}</dd></div>
          <div><dt>Total invested amount</dt><dd>{value(stats.total_invested)}</dd>
            <dd>All simulated buys, including fees · open basis {value(stats.open_cost_basis)}</dd></div>
          <div><dt>Unrealized P/L</dt><dd>{value(stats.unrealized_pnl)}</dd>
            <dd>{stats.valuation_complete ? "Against open FIFO cost basis" : "Full valuation needs a usable quote for every holding"}</dd></div>
          <div><dt>Realized P/L</dt><dd>{value(stats.realized_pnl)}</dd><dd>Simulated sales after fees</dd></div>
        </dl>
        <section className="portfolio-panel portfolio-freshness" aria-label="Market data freshness">
          <strong>Market data freshness</strong>
          <p>{freshness.open ? `${freshness.valued} of ${freshness.open} open positions valued.` : "No open positions to value."}
            {freshness.oldest && ` Oldest usable quote: ${formatTimestamp(freshness.oldest)}.`}</p>
          <p className="portfolio-muted">Quotes may be delayed. Each portfolio uses one currency. Exchange-rate conversion is unavailable, so quotes in other currencies or subunits are excluded from valuation.</p>
        </section>
        <PortfolioCharts snapshot={data} currency={currency} />
        <section className="portfolio-panel" aria-labelledby="portfolio-holdings-heading">
          <h2 id="portfolio-holdings-heading">Holdings</h2>
          <p className="portfolio-muted">Open simulated positions · FIFO cost basis · {currency}</p>
          {data.holdings.length > 0 ? <div className="portfolio-table-scroll" tabIndex={0} role="region" aria-label="Open portfolio holdings">
            <table className="portfolio-holdings">
              <thead><tr><th scope="col">Ticker</th><th scope="col">Shares</th><th scope="col">Cost basis</th><th scope="col">Market quote</th>
                <th scope="col">Market value</th><th scope="col">Unrealized P/L</th><th scope="col">Actions</th></tr></thead>
              <tbody>{data.holdings.map((holding) => {
                const quote = holding.market_quote;
                return <tr key={holding.ticker}>
                  <th scope="row">{holding.ticker}</th><td>{quantity.format(Number(holding.quantity))}</td>
                  <td>{value(holding.cost_basis)}</td>
                  <td>
                    {quote.price != null && <strong>{tradeMoney(quote.price, quote.currency)}</strong>}
                    <small>{quoteStatus(quote.status)}{quote.timestamp && ` · ${formatTimestamp(quote.timestamp)}`}</small>
                  </td><td>{value(holding.market_value)}</td><td>{value(holding.unrealized_pnl)}</td>
                  <td><button type="button" onClick={() => setDialog({ side: "sell", ticker: holding.ticker })}>Simulate sell</button></td>
                </tr>;
              })}</tbody>
            </table>
          </div> : <p className="portfolio-empty">No open positions. Record a simulated buy to get started.</p>}
        </section>
      </>}

      <section className="portfolio-panel" aria-labelledby="portfolio-history-heading">
        <h2 id="portfolio-history-heading">Trade history</h2>
        {!tradeHistory ? <p role="status">Loading simulated trades…</p>
          : tradeHistory.error ? <p role="alert" className="portfolio-alert">{tradeHistory.error}</p>
            : !tradeHistory.rows.length ? <p className="portfolio-empty">No simulated trades recorded yet.</p>
              : <div className="portfolio-table-scroll" tabIndex={0} role="region" aria-label="Simulated trade history">
                <table className="portfolio-trades"><thead><tr><th scope="col">Recorded</th><th scope="col">Ticker</th><th scope="col">Simulated action</th>
                  <th scope="col">Shares</th><th scope="col">Execution price</th><th scope="col">Fees</th></tr></thead>
                  <tbody>{tradeHistory.rows.map((trade) => <tr key={trade.id}>
                    <td>{formatTimestamp(trade.timestamp)}</td><th scope="row">{trade.ticker}</th>
                    <td>{trade.side === "buy" ? "Simulated buy" : "Simulated sell"}</td>
                    <td>{quantity.format(Number(trade.quantity))}</td>
                    <td>{tradeMoney(trade.price, trade.currency)}</td><td>{tradeMoney(trade.fees, trade.currency)}</td>
                  </tr>)}</tbody>
                </table>
              </div>}
        {tradeHistory?.moreError && <p className="portfolio-alert" role="alert">{tradeHistory.moreError}</p>}
        {tradeHistory?.next && <button type="button" onClick={moreTrades} disabled={more === key}>
          {more === key ? "Loading…" : "Load older trades"}
        </button>}
      </section>

      {data && <details className="portfolio-panel">
        <summary>Accounting and valuation details</summary>
        <ul>{data.notices.map((notice) => <li key={notice}>{notice}</li>)}</ul>
      </details>}
      {watchlistError && <p className="portfolio-muted">Watchlist suggestions are temporarily unavailable. You can still enter a ticker.</p>}
      {dialog && <VirtualTradeDialog portfolio={portfolio} initial={dialog} stocks={stocks} onClose={closeTrade}
        onRecorded={() => { closeTrade(); setRevision((previous) => previous + 1); setMessage("Simulated trade recorded."); }} />}
    </>}
  </main>;
}
