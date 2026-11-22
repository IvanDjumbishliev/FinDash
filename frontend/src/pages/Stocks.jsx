import { Link } from "react-router-dom";
import StockWatchlist from "../components/StockWatchlist";

const Stocks = () => {
  return (
    <div className="dashboard-shell">
      <div className="market-heading">
        <p className="eyebrow">Markets</p>
        <h1>Stock watchlist</h1>
        <p>Follow public companies, compare recent price trends, and see when market data was last reported. Quotes may be delayed.</p>
        <Link className="stock-simulator-link" to="/portfolios">Open virtual portfolio simulator</Link>
      </div>
      <StockWatchlist />
      <p className="stock-data-source">Market data from Yahoo Finance.</p>
    </div>
  );
};

export default Stocks;
