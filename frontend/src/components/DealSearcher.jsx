import { useState } from "react";
import "../styles/components/DealSearcher.css";
import api from "../api";

const OfferItem = ({ name, price, store, imageUrl }) => {
  return (
    <div className="offer-item">
      {imageUrl && (
        <img
          src={imageUrl}
          alt={name}
          className="store-logo"
          loading="lazy"
          onError={(event) => {
            event.currentTarget.style.display = "none";
          }}
        />
      )}
      <div className="deal-item">
        <span className="deal-name">{name}</span>
        {price && <span className="deal-value">{price}</span>}
        <span className="deal-store">{store}</span>
      </div>
    </div>
  );
};

const StoreItemGrid = ({ items, variant = "default" }) => {
  return (
    <div className={`deal-items-grid ${variant}`}>
      {items.map((item, index) => (
        <OfferItem
            name={item.name}
            price={item.price}
            store={item.store}
            imageUrl={item.image_url}
          key={index}
        />
      ))}
    </div>
  );
};

// export default Input;

const Deals = () => {
  const [searchQuery, setSearchQuery] = useState("");
  const [items, setItems] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [hasSearched, setHasSearched] = useState(false);

  const sendQuery = async () => {
    if (!searchQuery.trim()) {
      setError("Enter a product name to search.");
      return;
    }
    setError("");
    setHasSearched(true);
    setItems([]);
    setIsLoading(true);
    try {
      const results = await Promise.allSettled([
        api.get("/api/deals/lidl/"),
        api.get("/api/deals/kaufland/"),
        api.get("/api/deals/fantastico/"),
      ]);
      const lidlResponse =
        results[0].status === "fulfilled" ? results[0].value : null;
      const kauflandResponse =
        results[1].status === "fulfilled" ? results[1].value : null;
      const fantasticoResponse =
        results[2].status === "fulfilled" ? results[2].value : null;
      const combined = [
        ...(Array.isArray(lidlResponse?.data) ? lidlResponse.data : []),
        ...(Array.isArray(kauflandResponse?.data)
          ? kauflandResponse.data
          : []),
        ...(Array.isArray(fantasticoResponse?.data)
          ? fantasticoResponse.data
          : []),
      ];
      const query = searchQuery.trim().toLowerCase();
      setItems(
        combined.filter((item) =>
          String(item.name || "").toLowerCase().includes(query)
        )
      );
    } catch (error) {
      setError(
        error.response?.data?.error ||
        "Deal search is unavailable. Check that the backend is running and configured."
      );
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="deals-container-user">
      <h2>Deal searcher</h2>
      <table className="deals-table">
        <thead>
          <tr>
            <td colSpan="3" className="search-bar">
              <input
                type="text"
                placeholder="Example: milk, bread..."
                value={searchQuery}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    sendQuery();
                  }
                }}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setHasSearched(false);
                }}
                className="search-input"
              />
              <button className="search-button" onClick={sendQuery}>
                Search
              </button>
              {error && <p className="deal-search-error">{error}</p>}
            </td>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td colSpan="3">
              <div className="best-deals">
                <div className="best-deals-content">
                  {isLoading && (
                    <div>
                      <div className="loading-spinner spinner-fst"></div>
                      <div className="loading-spinner spinner-scn"></div>
                    </div>
                  )}
                  {!isLoading &&
                    (items.length > 0 ? (
                      <StoreItemGrid items={items} />
                    ) : (
                      <p className="deal-empty-state" role="status">
                        {error
                          ? "Search could not be completed."
                          : hasSearched
                            ? "No matching deals found."
                            : "Search for a product to see matching deals."}
                      </p>
                    ))}
                </div>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
};

export default Deals;
