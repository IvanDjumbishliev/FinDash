import { useEffect, useState } from "react";
import { FiArrowUpRight, FiRefreshCw } from "react-icons/fi";
import api from "../api";
import "../styles/pages/News.css";

const categories = [
  "All", "Markets", "Banking", "Business & economy", "Personal finance", "Cost of living",
];
const cacheKey = "findash-financial-news";
const maxCacheAge = 24 * 60 * 60 * 1000;

function readCachedNews() {
  try {
    const saved = JSON.parse(localStorage.getItem(cacheKey));
    if (Array.isArray(saved?.feed?.articles) && Date.now() - saved.savedAt < maxCacheAge) {
      return saved.feed;
    }
  } catch {
    // Storage may be unavailable.
  }
  return null;
}

function cacheNews(feed) {
  try {
    localStorage.setItem(cacheKey, JSON.stringify({ feed, savedAt: Date.now() }));
  } catch {
    // The current feed is still available in memory.
  }
}

function newsError(error) {
  if (!error.response) return "Could not reach the news service. Try refreshing in a moment.";
  if (error.response.status === 404) return "This backend is missing the News endpoint. It needs the latest FinDash version.";
  return error.response.data?.error || "Financial news is temporarily unavailable.";
}

const formatPublished = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

export default function News() {
  const [category, setCategory] = useState("All");
  const [feed, setFeed] = useState(readCachedNews);
  const [usingCache, setUsingCache] = useState(Boolean(feed));
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();

    async function load() {
      setLoading(true);
      setError("");
      try {
        const { data } = await api.get("/api/news/", {
          signal: controller.signal,
          timeout: 15000,
          headers: { Authorization: false },
        });
        if (controller.signal.aborted) return;
        if (!Array.isArray(data?.articles)) {
          setError("The server returned an unexpected response from the news endpoint.");
          setUsingCache(true);
        } else {
          setFeed(data);
          setUsingCache(false);
          if (data.articles.length) cacheNews(data);
        }
      } catch (requestError) {
        if (!controller.signal.aborted) {
          setError(newsError(requestError));
          setUsingCache(true);
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
          <p>Headlines from Bulgaria and around the world on markets, banking, and your money.</p>
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
      {error && (
        <p className="news-status" role="alert">
          {error}{feed?.articles.length > 0 && " Showing the last available headlines."}
        </p>
      )}
      {usingCache && feed && loading && (
        <p className="news-status" role="status">Checking for new headlines…</p>
      )}
      {feed?.partial && !error && (
        <p className="news-status" role="status">Some sources are temporarily unavailable.</p>
      )}
      {feed && !articles.length && !loading && !error && (
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
