import { Link } from "react-router-dom";
import StockWatchlist from "../components/StockWatchlist";

const Stocks = () => {
  return (
    <div className="dashboard-shell">
      <div className="market-heading">
        <p className="eyebrow">Markets</p>
        <h1>Stock watchlist</h1>
        <p>Search public stocks and track their one-month closing-price trend.</p>
        <Link className="stock-simulator-link" to="/portfolios">Open virtual portfolio simulator</Link>
      </div>
      <StockWatchlist />
    </div>
  );
};

export default Stocks;
