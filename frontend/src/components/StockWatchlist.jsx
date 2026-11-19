import "../styles/components/StockWatchlist.css";
import { useState, useEffect } from "react";
import api from "../api";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";

const StockWatchlist = () => {
  const [watchlist, setWatchlist] = useState([]);
  const [newSymbol, setNewSymbol] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [watchlistError, setWatchlistError] = useState("");

  useEffect(() => {
    loadWatchlist();
  }, []);

  const loadWatchlist = async () => {
    try {
      const response = await api.get("/api/stocks/watchlist/");
      setWatchlist(response.data.stocks || []);
      setWatchlistError("");
    } catch (error) {
      setWatchlistError(
        error.response?.data?.error || "Unable to load your stock watchlist."
      );
    }
  };

  const searchStocks = async (query) => {
    if (query.length < 2) {
      setSearchResults([]);
      setSearchError("");
      return;
    }
    setSearchError("");
    setIsSearching(true);
    try {
      const response = await api.get(`/api/stocks/search/`, {
        params: { query },
      });
      setSearchResults(response.data);
    } catch (error) {
      setSearchResults([]);
      setSearchError(
        error.response?.data?.error || "Unable to search stocks right now."
      );
    } finally {
      setIsSearching(false);
    }
  };

  const handleSearchChange = (e) => {
    const value = e.target.value;
    setNewSymbol(value);
    searchStocks(value);
  };

  const handleSelectStock = async (stock) => {
    try {
      await api.post("/api/stocks/watchlist/", { symbol: stock.symbol });
      await loadWatchlist(); // Refresh the watchlist from backend
      setSearchResults([]);
      setNewSymbol("");
    } catch (error) {
      setSearchError(
        error.response?.data?.error || "Unable to add this stock right now."
      );
    }
  };

  return (
    <div className="SW-container">
      <div className="relative">
        <input
          type="text"
          value={newSymbol}
          onChange={handleSearchChange}
          placeholder="Search stock symbol or name"
          className="search-btn-stocks"
        />
        {isSearching && (
          <div className="text-sm text-gray-500">Searching...</div>
        )}
        {searchError && <p className="stock-status" role="status">{searchError}</p>}
        {searchResults.length > 0 && (
          <div className="result-stocks first">
            {searchResults.map((stock) => (
              <div
                key={stock.symbol}
                onClick={() => handleSelectStock(stock)}
                className="result-stocks second"
              >
                <span className="font-bold">{stock.symbol}</span> -{" "}
                <span>{stock.name}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="charts-container">
        {watchlistError && (
          <p className="stock-status" role="alert">{watchlistError}</p>
        )}
        {watchlist.map((stock) => (
          <div key={stock.symbol} className="chart-item">
            <div className="chart-item-container">
              <h3>
                {stock.name} ({stock.symbol})
              </h3>
              {stock.history?.length ? (
                <div className="chart">
                  <ResponsiveContainer width="100%" height={300}>
                    <LineChart data={stock.history}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="date" />
                      <YAxis />
                      <Tooltip />
                      <Line
                        type="monotone"
                        dataKey="price"
                        stroke="#6d5dfc"
                        dot={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <p className="stock-status" role="status">
                  {stock.error || "No data available"}
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default StockWatchlist;
