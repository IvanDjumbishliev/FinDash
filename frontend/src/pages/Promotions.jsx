import { useEffect, useState } from "react";
import api from "../api";
import Deals from "../components/Deals";
import DealSearcher from "../components/DealSearcher";
import kauflandLogo from "../assets/kaufland-logo.svg";
import lidlLogo from "../assets/lidl-logo.svg";
import fantasticoLogo from "../assets/fantastico-logo.png";
import "../styles/pages/Promotion.css";

const stores = [
  { id: "kaufland", name: "Kaufland", image: kauflandLogo },
  { id: "lidl", name: "Lidl", image: lidlLogo },
  { id: "fantastico", name: "Фантастико", image: fantasticoLogo },
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
