import StockWatchlist from "../components/StockWatchlist";

const Stocks = () => {
  return (
    <div className="container mx-auto px-4 py-8">
      <div className="market-heading">
        <p className="eyebrow">Markets</p>
        <h1>Stock watchlist</h1>
        <p>Search public stocks and track their one-month closing-price trend.</p>
      </div>
      <StockWatchlist />
    </div>
  );
};

export default Stocks;
