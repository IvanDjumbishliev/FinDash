import { useState } from "react";
import "../styles/components/DealSearcher.css";
import kaufland from "../assets/kaufland.png";
import lidl from "../assets/lidl.png";
import billa from "../assets/billa.png";
import cross from "../assets/cross.png";
import api from "../api";

const OfferItem = ({ name, value, store }) => {
  let isPromptValid = true;
  const getStoreLogo = (storeName) => {
    switch ((storeName || "").toLowerCase()) {
      case "kaufland":
        return kaufland;
      case "lidl":
        return lidl;
      case "billa":
        return billa;
      case "x":
        isPromptValid = false;
        return cross;
      default:
        isPromptValid = false;
        return cross;
    }
  };
  return (
    <div className="offer-item">
      <img
        src={getStoreLogo(store)}
        alt={`${store} logo`}
        className="store-logo"
      />
      <div className="deal-item">
        <span className="deal-name">{name}</span>
        {isPromptValid && <span className="deal-value">-{value}%</span>}
      </div>
    </div>
  );
};

const StoreItemGrid = ({ items, variant = "default" }) => {
  return (
    <div className={`deal-items-grid ${variant}`}>
      {items.map((item, index) => (
        <OfferItem
          name={item.info}
          value={item.discount}
          store={item.supermarket}
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
      const response = await api.post("/api/leaflet/user/", {
        prompt: searchQuery,
      });
      const results = Array.isArray(response.data.response)
        ? response.data.response
        : [];
      setItems(
        results.filter(
          (item) =>
            String(item?.info || "").toLowerCase() !== "no deals found" &&
            String(item?.info || "").toLowerCase() !== "invalid request"
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
