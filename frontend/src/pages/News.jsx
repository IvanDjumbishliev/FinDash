import { useEffect, useState } from "react";
import { FiArrowUpRight, FiRefreshCw } from "react-icons/fi";
import api from "../api";
import "../styles/pages/News.css";

const categories = ["All", "Markets", "Banking", "Business & economy", "Personal finance"];
const formatPublished = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

export default function News() {
  const [category, setCategory] = useState("All");
  const [feed, setFeed] = useState(null);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();

    async function load() {
      setLoading(true);
      setError("");
      try {
        const { data } = await api.get("/api/news/", { signal: controller.signal });
        if (!controller.signal.aborted) setFeed(data);
      } catch (requestError) {
        if (!controller.signal.aborted) {
          setError(requestError.response?.data?.error || "Unable to load financial news.");
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }

    load();
    const timer = window.setInterval(load, 10 * 60 * 1000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [refresh]);

  const articles = (feed?.articles ?? []).filter(
    (article) => category === "All" || article.categories.includes(category)
  );

  return (
    <main className="dashboard-shell news-page">
      <header className="news-heading">
        <div>
          <h1>Financial news</h1>
          <p>Latest headlines on markets, banking, the economy, and personal finance.</p>
        </div>
        <button
          className="news-refresh"
          type="button"
          disabled={loading}
          onClick={() => setRefresh((previous) => previous + 1)}
        >
          <FiRefreshCw aria-hidden="true" />
          Refresh
        </button>
      </header>

      <div className="news-filters" role="group" aria-label="Filter news by topic">
        {categories.map((topic) => (
          <button
            key={topic}
            type="button"
            aria-pressed={topic === category}
            onClick={() => setCategory(topic)}
          >
            {topic}
          </button>
        ))}
      </div>

      {loading && !feed && <p className="news-status" role="status">Loading headlines…</p>}
      {error && <p className="news-status" role="alert">{error}</p>}
      {feed?.partial && !error && (
        <p className="news-status" role="status">Some sources are temporarily unavailable.</p>
      )}
      {feed && !articles.length && !loading && (
        <p className="news-status" role="status">No headlines from the past week in this view.</p>
      )}

      <ul className="news-grid">
        {articles.map((article) => (
          <li key={article.url}>
            <article className="news-card">
              <p className="news-category">
                {category === "All" ? article.categories.join(" · ") : category}
              </p>
              <h2>
                <a href={article.url} target="_blank" rel="noopener noreferrer">
                  {article.title}
                  <FiArrowUpRight aria-hidden="true" />
                </a>
              </h2>
              <p className="news-source">
                <span>{article.source}</span>
                <time dateTime={article.published_at}>
                  {formatPublished.format(new Date(article.published_at))}
                </time>
              </p>
            </article>
          </li>
        ))}
      </ul>
    </main>
  );
}
