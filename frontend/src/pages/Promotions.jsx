import { useEffect, useState } from "react";
import api from "../api";
import Deals from "../components/Deals";
import DealSearcher from "../components/DealSearcher";
import kaufland from "../assets/kaufland.png";
import lidl from "../assets/lidl.png";
import "../styles/pages/Promotion.css";

const stores = [
  { id: "kaufland", name: "Kaufland", image: kaufland },
  { id: "lidl", name: "Lidl", image: lidl },
  { id: "fantastico", name: "Фантастико" },
];

export default function Promotions() {
  const [results, setResults] = useState({});

  useEffect(() => {
    const controller = new AbortController();
    for (const { id } of stores) {
      api.get(`/api/deals/${id}/`, { signal: controller.signal })
        .then(({ data }) => Array.isArray(data) ? { items: data } : { error: true })
        .catch(() => ({ error: true }))
        .then((result) => {
          if (!controller.signal.aborted) {
            setResults((previous) => ({ ...previous, [id]: result }));
          }
        });
    }
    return () => controller.abort();
  }, []);

  return (
    <div className="promotions-container fade-in">
      <Deals stores={stores} results={results} />
      <DealSearcher stores={stores} results={results} />
    </div>
  );
}
