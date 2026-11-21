import { useState } from "react";
import { FiArrowLeft, FiArrowRight, FiBell, FiSettings } from "react-icons/fi";
import { Link } from "react-router-dom";
import { MarkAllRead, NotificationList, NotificationState } from "../components/NotificationInbox";
import { useNotificationInbox, useNotificationQuery } from "../components/notificationContext";
import { categories } from "../notifications";

const PAGE_SIZE = 20;

export default function Notifications() {
  const [category, setCategory] = useState("");
  const [filter, setFilter] = useState("all");
  const [offset, setOffset] = useState(0);
  const { feedback } = useNotificationInbox();
  const query = useNotificationQuery({
    limit: PAGE_SIZE, offset, category, unread: filter === "unread", dismissed: filter === "history",
  });
  const total = query.data?.count ?? 0;
  const rows = query.data?.results || [];

  return <main className="notification-page">
    <header className="notification-page-header">
      <div>
        <h1><FiBell aria-hidden="true" /> Notifications</h1>
        <p>{query.data ? `${query.data.unread_count} unread` : "Your FinDash activity"}</p>
      </div>
      <Link className="notification-secondary" to="/notifications/settings"><FiSettings aria-hidden="true" /> Settings</Link>
    </header>
    <section className="notification-panel" aria-label="Notification history">
      <div className="notification-filters">
        <label>Category
          <select value={category} onChange={(event) => { setCategory(event.target.value); setOffset(0); }}>
            <option value="">All categories</option>
            {Object.entries(categories).map(([key, item]) => <option key={key} value={key}>{item.label}</option>)}
          </select>
        </label>
        <label>Status
          <select value={filter} onChange={(event) => { setFilter(event.target.value); setOffset(0); }}>
            <option value="all">Inbox</option>
            <option value="unread">Unread</option>
            <option value="history">Include dismissed</option>
          </select>
        </label>
        <MarkAllRead count={query.data?.unread_count} />
      </div>
      <p className="notification-feedback" role="status">{feedback}</p>
      <NotificationState query={query} empty={category || filter !== "all"
        ? "No notifications match these filters."
        : "You're all caught up. New FinDash alerts will appear here."} />
      {rows.length > 0 && <NotificationList items={rows} full />}
      {(offset > 0 || query.data?.next) && <nav className="notification-pagination" aria-label="Notification history pages">
        <button type="button" className="notification-secondary" disabled={!offset} onClick={() => setOffset(offset - PAGE_SIZE)}>
          <FiArrowLeft aria-hidden="true" /> Previous
        </button>
        <span aria-live="polite">{rows.length ? `${offset + 1}–${offset + rows.length} of ${total}` : ""}</span>
        <button type="button" className="notification-secondary" disabled={!query.data?.next} onClick={() => setOffset(offset + PAGE_SIZE)}>
          Next <FiArrowRight aria-hidden="true" />
        </button>
      </nav>}
    </section>
  </main>;
}
