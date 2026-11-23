import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import PropTypes from "prop-types";
import { FiAlertCircle, FiBarChart2, FiBell, FiCalendar, FiCheck, FiFileText, FiTrendingUp, FiUpload } from "react-icons/fi";
import { displayDate, money } from "../copilotPresentation";
import api from "../api";
import { ACCESS_TOKEN } from "../constants";
import { categories, notificationPath } from "../notifications";
import { InboxContext, notificationAccount, useNotificationInbox } from "./notificationContext";

const icons = {
  budget_threshold: FiBarChart2,
  subscription_renewal: FiCalendar,
  unusual_spending: FiAlertCircle,
  statement_import: FiUpload,
  financial_report: FiFileText,
  stock_threshold: FiTrendingUp,
};
const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

export function NotificationProvider({ account, children }) {
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState("");
  const active = useRef(false);

  async function mutate(action, successMessage) {
    if (active.current || account === null || notificationAccount() !== account) return;
    active.current = true;
    setBusy(true);
    setFeedback("");
    const headers = { Authorization: `Bearer ${localStorage.getItem(ACCESS_TOKEN)}` };
    try {
      await action(headers);
      if (notificationAccount() === account) setFeedback(successMessage);
    } catch {
      if (notificationAccount() === account) setFeedback("Could not update notifications. Try again.");
    } finally {
      active.current = false;
      if (notificationAccount() === account) {
        setBusy(false);
        setRevision((value) => value + 1);
      }
    }
  }

  const value = {
    account, busy, feedback, revision,
    markAll: () => mutate((headers) => api.post(`${notificationPath}mark-all-read/`, {}, { headers, timeout: 8_000 }),
      "All notifications marked as read."),
    toggleRead: (item) => mutate((headers) => api.patch(`${notificationPath}${item.id}/`, { read: !item.read },
      { headers, timeout: 8_000 }), item.read ? "Notification marked as unread." : "Notification marked as read."),
    changeDismissed: (item) => mutate((headers) => api.patch(`${notificationPath}${item.id}/`, { dismissed: !item.dismissed },
      { headers, timeout: 8_000 }), item.dismissed ? "Notification restored." : "Notification dismissed."),
  };
  return <InboxContext.Provider value={value}>{children}</InboxContext.Provider>;
}

export function NotificationList({ items, full = false }) {
  const { busy, toggleRead, changeDismissed } = useNotificationInbox();
  return <ul className="notification-list">
    {items.map((item) => {
      const Icon = icons[item.category] || FiBell;
      return <li key={item.id} className={item.read ? "notification-item" : "notification-item notification-item-unread"}>
        <div className="notification-icon"><Icon aria-hidden="true" /></div>
        <div className="notification-item-copy">
          <div className="notification-item-meta">
            <span>{categories[item.category]?.label || "Notification"}</span>
            <time dateTime={item.created_at}>{dateFormat.format(new Date(item.created_at))}</time>
          </div>
          <p className="notification-title">{item.title}</p>
          <p className="notification-message">{item.message}</p>
          {item.category === "warranty_expiration" && item.payload?.product && <div className="notification-message">
            <strong>{item.payload.product}</strong> · Expires {displayDate(item.payload.expires_on)}
            <div><Link className="dash-link" to="/warranties">Open Warranty Vault</Link></div>
          </div>}
          {item.category === "grocery_deal" && Array.isArray(item.payload?.deals) && <ul className="notification-deal-details">
            {item.payload.deals.map((deal, index) => <li key={`${deal.offer_id}-${index}`}>
              <strong>{deal.product}</strong> · {deal.retailer} · {money(deal.price, deal.currency)}
              <div>Advertised through {deal.expires_at ? dateFormat.format(new Date(deal.expires_at)) : displayDate(deal.expires_on)}</div>
              {deal.reasons.map((reason) => <div key={reason}>{reason}</div>)}
            </li>)}
          </ul>}
          <div className="notification-item-actions">
            {!item.read && <span className="notification-unread">Unread</span>}
            {item.dismissed && <span>Dismissed</span>}
            <button type="button" aria-disabled={busy} onClick={() => toggleRead(item)}
              aria-label={`${item.read ? "Mark unread" : "Mark read"}: ${item.title}`}>
              {item.read ? "Mark unread" : "Mark read"}
            </button>
            {full && <button type="button" aria-disabled={busy} onClick={() => changeDismissed(item)}
              aria-label={`${item.dismissed ? "Restore" : "Dismiss"}: ${item.title}`}>
              {item.dismissed ? "Restore" : "Dismiss"}
            </button>}
          </div>
        </div>
      </li>;
    })}
  </ul>;
}

export function MarkAllRead({ count }) {
  const { busy, markAll } = useNotificationInbox();
  return <button type="button" className="notification-secondary" onClick={() => { if (count) markAll(); }} aria-disabled={busy || !count}>
    <FiCheck aria-hidden="true" /> Mark all as read
  </button>;
}

export function NotificationState({ query, empty }) {
  if (query.offline) return <div className="notification-callout" role="status">
    <p>You’re offline. Notifications will refresh when you reconnect.</p>
  </div>;
  if (query.error) return <div className="notification-callout" role="status">
    <p>{query.data ? "Updates are temporarily unavailable. Showing the last loaded notifications." : "Could not load notifications."}</p>
    <button type="button" className="notification-secondary" onClick={query.retry}>Retry</button>
  </div>;
  if (!query.data) return <div className="notification-loading" role="status">Loading notifications…</div>;
  if (query.data.results.length === 0) return <div className="notification-callout"><p>{empty}</p></div>;
  return null;
}

NotificationProvider.propTypes = {
  account: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
  children: PropTypes.node.isRequired,
};

NotificationList.propTypes = {
  items: PropTypes.arrayOf(PropTypes.shape({
    id: PropTypes.number.isRequired,
    category: PropTypes.string.isRequired,
    title: PropTypes.string.isRequired,
    message: PropTypes.string.isRequired,
    created_at: PropTypes.string.isRequired,
    read: PropTypes.bool.isRequired,
    dismissed: PropTypes.bool.isRequired,
  })).isRequired,
  full: PropTypes.bool,
};

MarkAllRead.propTypes = { count: PropTypes.number };

NotificationState.propTypes = {
  query: PropTypes.shape({
    offline: PropTypes.bool.isRequired,
    error: PropTypes.bool,
    data: PropTypes.shape({ results: PropTypes.array.isRequired }),
    retry: PropTypes.func.isRequired,
  }).isRequired,
  empty: PropTypes.string.isRequired,
};
