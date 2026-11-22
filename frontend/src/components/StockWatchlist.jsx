import { useEffect, useState } from "react";
import StockMarketCard from "./StockMarketCard";
import api from "../api";
import "../styles/components/StockWatchlist.css";

const WATCHLIST_URL = "/api/stocks/watchlist/";
const MARKET_BATCH_SIZE = 5;

function getStocks(data) {
  if (!Array.isArray(data?.stocks)) throw new Error("Invalid watchlist response.");
  return data.stocks;
}

export default function StockWatchlist() {
  const [watchlist, setWatchlist] = useState([]);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState(null);
  const [adding, setAdding] = useState(null);
  const [addError, setAddError] = useState("");
  const [watchlistError, setWatchlistError] = useState("");
  const [marketLoading, setMarketLoading] = useState(false);
  const [marketError, setMarketError] = useState(false);
  const [watchlistLoading, setWatchlistLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const term = query.trim();
  const result = search?.term === term ? search : null;

  useEffect(() => {
    const controller = new AbortController();
    const options = { signal: controller.signal, timeout: 20_000 };

    async function loadWatchlist() {
      let stocks;
      try {
        const { data } = await api.get(WATCHLIST_URL, { ...options, params: { include_history: false } });
        stocks = getStocks(data);
        if (controller.signal.aborted) return;
        setWatchlist((previous) => {
          const existing = new Map(previous.map((stock) => [stock.symbol, stock]));
          return stocks.map((stock) => ({ ...existing.get(stock.symbol), ...stock }));
        });
      } catch (error) {
        if (!controller.signal.aborted) {
          const message = error.response?.status === 401
            ? "Your session has expired. Sign in again to load your watchlist."
            : "Unable to load your saved stocks. Try again.";
          setWatchlistError(message);
        }
        return;
      } finally {
        if (!controller.signal.aborted) setWatchlistLoading(false);
      }

      if (!stocks.length) return;
      setMarketLoading(true);
      try {
        for (let index = 0; index < stocks.length && !controller.signal.aborted; index += MARKET_BATCH_SIZE) {
          const params = new URLSearchParams();
          for (const stock of stocks.slice(index, index + MARKET_BATCH_SIZE)) params.append("symbol", stock.symbol);
          try {
            const { data } = await api.get(WATCHLIST_URL, { ...options, params });
            const market = new Map(getStocks(data).map((stock) => [stock.symbol, stock]));
            if (controller.signal.aborted) return;
            setWatchlist((previous) => previous.map((stock) => market.get(stock.symbol) ?? stock));
          } catch {
            if (controller.signal.aborted) return;
            setMarketError(true);
            break;
          }
        }
      } finally {
        if (!controller.signal.aborted) setMarketLoading(false);
      }
    }

    loadWatchlist();
    return () => controller.abort();
  }, [refresh]);

  useEffect(() => {
    if (!term) return;

    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const { data } = await api.get("/api/stocks/search/", {
          params: { query: term },
          signal: controller.signal,
          timeout: 12_000,
        });
        if (!controller.signal.aborted) setSearch({ term, stocks: data });
      } catch (error) {
        if (!controller.signal.aborted) {
          const message = error.response?.data?.error || "Unable to search stocks right now.";
          setSearch({ term, stocks: [], message });
        }
      }
    }, 300);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [term]);

  function reloadWatchlist() {
    setWatchlistLoading(true);
    setWatchlistError("");
    setMarketLoading(false);
    setMarketError(false);
    setRefresh((previous) => previous + 1);
  }

  async function addStock(stock) {
    setAddError("");
    setAdding(stock.symbol);
    try {
      await api.post(WATCHLIST_URL, { symbol: stock.symbol }, { timeout: 12_000 });
      setWatchlist((previous) => [
        ...previous.filter(({ symbol }) => symbol !== stock.symbol),
        stock,
      ]);
      setQuery("");
      setSearch(null);
      reloadWatchlist();
    } catch (error) {
      setAddError(error.response?.data?.error || "Unable to add this stock right now.");
    } finally {
      setAdding(null);
    }
  }

  return (
    <section className="stock-watchlist">
      <div className="stock-search">
        <label htmlFor="stock-query">Find a stock</label>
        <input
          id="stock-query"
          type="search"
          value={query}
          maxLength={100}
          disabled={Boolean(adding)}
          onChange={(event) => {
            const next = event.target.value;
            if (next.trim() !== term) setSearch(null);
            setQuery(next);
            setAddError("");
          }}
          placeholder="Company name or ticker, e.g. Apple or AAPL"
        />
        {term && !result && <p role="status" className="stock-status">Searching…</p>}
        {result?.message && <p role="status" className="stock-status">{result.message}</p>}
        {addError && <p role="alert" className="stock-status">{addError}</p>}
        {result?.stocks.length > 0 && (
          <ul className="stock-search-results">
            {result.stocks.map((stock) => {
              const saved = watchlist.some(({ symbol }) => symbol === stock.symbol);
              return (
                <li key={stock.symbol}>
                  <button type="button" disabled={saved || Boolean(adding)} onClick={() => addStock(stock)}>
                    <span><strong>{stock.symbol}</strong> · {stock.name}{stock.exchange && <small className="stock-result-exchange">{stock.exchange}</small>}</span>
                    <span>{saved ? "Added" : adding === stock.symbol ? "Adding…" : "Add"}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {watchlistLoading && <p role="status" className="stock-status">Loading watchlist…</p>}
      {watchlistError && <p role="alert" className="stock-status">{watchlistError}</p>}
      {marketError && <p role="alert" className="stock-status">Some market details could not load. Your saved stocks are shown below.</p>}
      {(watchlistError || marketError || watchlist.some(({ error }) => error)) && !watchlistLoading && !marketLoading && (
        <button className="stock-retry" type="button" onClick={reloadWatchlist}>Retry loading</button>
      )}
      {!watchlist.length && !watchlistLoading && !watchlistError && (
        <p className="stock-status">Your watchlist is empty. Search above to add a stock.</p>
      )}
      <div className="stock-charts">
        {watchlist.map((stock) => (
          <StockMarketCard key={stock.symbol} stock={stock} loading={watchlistLoading || marketLoading} />
        ))}
      </div>
    </section>
  );
}
