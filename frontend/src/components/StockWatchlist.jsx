import { useEffect, useState } from "react";
import StockMarketCard from "./StockMarketCard";
import api from "../api";
import "../styles/components/StockWatchlist.css";

export default function StockWatchlist() {
  const [watchlist, setWatchlist] = useState([]);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState(null);
  const [adding, setAdding] = useState(null);
  const [addError, setAddError] = useState("");
  const [watchlistError, setWatchlistError] = useState("");
  const [watchlistLoading, setWatchlistLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const term = query.trim();
  const result = search?.term === term ? search : null;

  useEffect(() => {
    const controller = new AbortController();
    api.get("/api/stocks/watchlist/", { signal: controller.signal })
      .then(({ data }) => {
        if (!controller.signal.aborted) {
          setWatchlist(data.stocks);
          setWatchlistError("");
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setWatchlistError(error.response?.data?.error || "Unable to load your stock watchlist.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setWatchlistLoading(false);
      });
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
    setRefresh((previous) => previous + 1);
  }

  async function addStock(stock) {
    setAddError("");
    setAdding(stock.symbol);
    try {
      await api.post("/api/stocks/watchlist/", { symbol: stock.symbol });
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
      {(watchlistError || watchlist.some(({ error }) => error)) && !watchlistLoading && (
        <button className="stock-retry" type="button" onClick={reloadWatchlist}>Retry loading</button>
      )}
      {!watchlist.length && !watchlistLoading && !watchlistError && (
        <p className="stock-status">Your watchlist is empty. Search above to add a stock.</p>
      )}
      <div className="stock-charts">
        {watchlist.map((stock) => (
          <StockMarketCard key={stock.symbol} stock={stock} loading={watchlistLoading} />
        ))}
      </div>
    </section>
  );
}
