import { useState, useEffect } from "react";
import "../styles/components/Deals.css";
import kaufland from "../assets/kaufland.png";
import lidl from "../assets/lidl.png";
import api from "../api";

const StoreButton = ({ id, isActive, onClick, image }) => {
  return (
    <button
      id={id}
      className={`button ${isActive ? "active" : ""}`}
      onClick={onClick}
    >
      <img src={image} alt={id} />
    </button>
  );
};

const StoreItemGrid = ({ items }) => {
  if (!items.length) {
    return <p className="deal-empty-state" role="status">No deals loaded yet</p>;
  }
  return (
    <div className="deal-items-grid">
      {items.map((item, index) => (
        <div className="deal-item deal-card" key={`${item.store}-${item.name}-${index}`}>
          {item.image_url && (
            <img
              className="deal-card-image"
              src={item.image_url}
              alt={item.name}
              loading="lazy"
              onError={(event) => {
                event.currentTarget.style.display = "none";
              }}
            />
          )}
          <div className="deal-card-copy">
            <span className="deal-name">{item.name}</span>
            {item.price && <span className="deal-value">{item.price}</span>}
          </div>
        </div>
      ))}
    </div>
  );
};

const Deals = ({ isFetched }) => {
  const [activeStore, setActiveStore] = useState("lidl");
  const [kaudflandItems, setKauflandItems] = useState([]);
  const [lidlItems, setLidlItems] = useState([]);
  const [fantasticoItems, setFantasticoItems] = useState([]);
  const [isLoading, setIsLoading] = useState(false);

  const fetchFantasticoDeals = async () => {
    try {
      const response = await api.get("/api/deals/fantastico/");
      if (response.status === 200) {
        setFantasticoItems(Array.isArray(response.data) ? response.data : []);
      }
    } catch {
      setFantasticoItems([]);
    }
  };

  const fetchKauflandDeals = async () => {
    try {
      const response = await api.get("/api/deals/kaufland/");
      if (response.status === 200) {
        setKauflandItems(Array.isArray(response.data) ? response.data : []);
      }
    } catch (error) {
      setKauflandItems([]);
    }
  };

  const fetchLidlDeals = async () => {
    try {
      const response = await api.get("/api/deals/lidl/");
      if (response.status === 200) {
        setLidlItems(Array.isArray(response.data) ? response.data : []);
      }
    } catch (error) {
      setLidlItems([]);
    }
  };

  useEffect(() => {
    const loadDeals = async () => {
      setIsLoading(true);
      try {
        await Promise.all([
          fetchKauflandDeals(),
          fetchLidlDeals(),
          fetchFantasticoDeals(),
        ]);
        isFetched?.();
      } catch {
        setKauflandItems([]);
        setLidlItems([]);
        setFantasticoItems([]);
      } finally {
        setIsLoading(false);
      }
    };

    loadDeals();
  }, [isFetched]);

  const handleClick = (store) => {
    setActiveStore(store);
  };

  return (
    <div className="deals-container">
      <h2>Best deals right now</h2>
      <table className="deals-table">
        <thead>
          <tr>
            <td>
              <StoreButton
                id="kaufland"
                isActive={activeStore === "kaufland"}
                onClick={() => handleClick("kaufland")}
                image={kaufland}
              />
            </td>
            <td>
              <StoreButton
                id="lidl"
                isActive={activeStore === "lidl"}
                onClick={() => handleClick("lidl")}
                image={lidl}
              />
            </td>
            <td>
              <button
                id="fantastico"
                className={`button fantastico-button ${activeStore === "fantastico" ? "active" : ""}`}
                onClick={() => handleClick("fantastico")}
                aria-label="Fantastico"
              >
                <img
                  src="https://www.fantastico.bg/images/f-logo-latest.png"
                  alt="Fantastico"
                  className="fantastico-logo-image"
                  onError={(event) => {
                    event.currentTarget.style.display = "none";
                  }}
                />
              </button>
            </td>
          </tr>
        </thead>
        <tbody>
          <tr>
            {isLoading ? (
              <td colSpan="3">
                <div className="spinner-container">
                  <div className="loading-spinner spinner-fst"></div>
                  <div className="loading-spinner spinner-scn"></div>
                </div>
              </td>
            ) : (
              <td colSpan="3">
                <div
                  className={`deals-content ${
                    activeStore === "kaufland" ? "active" : ""
                  }`}
                >
                  <StoreItemGrid items={kaudflandItems} />
                </div>
                <div
                  className={`deals-content ${
                    activeStore === "lidl" ? "active" : ""
                  }`}
                >
                  <StoreItemGrid items={lidlItems} />
                </div>
                <div
                  className={`deals-content ${
                    activeStore === "fantastico" ? "active" : ""
                  }`}
                >
                  <StoreItemGrid items={fantasticoItems} />
                </div>
              </td>
            )}
          </tr>
        </tbody>
      </table>
    </div>
  );
};

export default Deals;
