import { useEffect, useId, useRef, useState } from "react";
import { FiArrowRight, FiBell, FiSettings } from "react-icons/fi";
import { Link } from "react-router-dom";
import { MarkAllRead, NotificationList, NotificationState } from "./NotificationInbox";
import { useNotificationInbox, useNotificationQuery } from "./notificationContext";

export default function NotificationBell() {
  const [open, setOpen] = useState(false);
  const id = useId();
  const wrapper = useRef(null);
  const trigger = useRef(null);
  const { feedback } = useNotificationInbox();
  const query = useNotificationQuery({ limit: 5 });
  const unread = query.data?.unread_count ?? 0;

  useEffect(() => {
    if (!open) return;
    function outside(event) {
      if (!wrapper.current?.contains(event.target)) setOpen(false);
    }
    function escape(event) {
      if (event.key !== "Escape" || !wrapper.current?.contains(document.activeElement)) return;
      setOpen(false);
      trigger.current?.focus();
    }
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  return <div className="notification-bell-wrap" ref={wrapper} onBlur={(event) => {
    if (event.relatedTarget && !event.currentTarget.contains(event.relatedTarget)) setOpen(false);
  }}>
    <button ref={trigger} type="button" className="notification-bell" aria-controls={id} aria-expanded={open}
      aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
      onClick={() => {
        if (!open) query.retry();
        setOpen(!open);
      }}>
      <FiBell aria-hidden="true" />
      {unread > 0 && <span className="notification-badge" aria-hidden="true">{unread > 99 ? "99+" : unread}</span>}
    </button>
    <section className="notification-popover" id={id} hidden={!open} aria-label="Recent notifications">
      {open && <>
        <header className="notification-popover-header">
          <h2>Notifications</h2>
          <MarkAllRead count={unread} />
        </header>
        <div className="notification-popover-scroll">
          <NotificationState query={query} empty="You're all caught up." />
          {query.data?.results.length > 0 && <NotificationList items={query.data.results} />}
        </div>
        <p className="notification-feedback" role="status">{feedback}</p>
        <footer className="notification-popover-footer">
          <Link to="/notifications/settings" onClick={() => setOpen(false)}><FiSettings aria-hidden="true" /> Settings</Link>
          <Link to="/notifications" onClick={() => setOpen(false)}>View all <FiArrowRight aria-hidden="true" /></Link>
        </footer>
      </>}
    </section>
  </div>;
}
