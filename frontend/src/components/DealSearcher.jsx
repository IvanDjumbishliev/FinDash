import { dealResults, storeList } from "./dealProps";
import { useState } from "react";
import { StoreItemGrid } from "./Deals";
import "../styles/components/DealSearcher.css";

const searchWords = (value) =>
  value.normalize("NFKC").toLocaleLowerCase("bg").match(/[\p{L}\p{N}]+/gu) ?? [];

export default function DealSearcher({ stores, results }) {
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const words = searchWords(query);
  const pending = stores.some(({ id }) => !results[id]);
  const unavailable = stores
    .filter(({ id }) => results[id] && !results[id].items?.length)
    .map(({ name }) => name);
  const matches = words.length
    ? stores.flatMap(({ id, name }) =>
        (results[id]?.items ?? [])
          .filter((item) => {
            const productName = searchWords(item.name ?? "").join(" ");
            return words.every((word) => productName.includes(word));
          })
          .map((item) => ({ ...item, storeName: name }))
      )
    : [];

  function submit(event) {
    event.preventDefault();
    if (!searchWords(input).length) {
      setQuery("");
      setError("Enter a product name to search.");
      return;
    }
    setError("");
    setQuery(input.trim());
  }

  return (
    <section className="deals-container deals-container-user" aria-labelledby="deal-search-title">
      <h2 id="deal-search-title">Deal searcher</h2>
      <form className="search-bar" role="search" onSubmit={submit}>
        <input
          type="search"
          aria-label="Product name"
          placeholder="Example: мляко, хляб…"
          value={input}
          onChange={(event) => {
            setInput(event.target.value);
            setError("");
          }}
          className="search-input"
        />
        <button type="submit" className="search-button">Search</button>
      </form>
      <div className="deals-content" role="region" aria-label="Deal search results" tabIndex={0}>
        {error && <p className="deal-empty-state" role="alert">{error}</p>}
        {!error && (
          <p className="deal-search-status" role="status">
            {!query
              ? "Search for a product across all three stores."
              : pending
                ? `Still loading offers. ${matches.length} matches so far.`
                : `${matches.length ? `${matches.length} matching offers` : "No matching offers"} for “${query}”.`}
          </p>
        )}
        {query && unavailable.length > 0 && (
          <p className="deal-search-status">Offers unavailable for {unavailable.join(", ")}.</p>
        )}
        {matches.length > 0 && <StoreItemGrid items={matches} />}
      </div>
    </section>
  );
}

DealSearcher.propTypes = { stores: storeList.isRequired, results: dealResults.isRequired };
