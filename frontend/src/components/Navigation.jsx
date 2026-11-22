import { useEffect, useId, useRef, useState } from "react";
import { FiChevronDown } from "react-icons/fi";
import ThemeToggle from "./ThemeToggle";
import NotificationBell from "./NotificationBell";
import { useNotificationInbox } from "./notificationContext";
import { NavLink, Link } from "react-router-dom";
import "../styles/components/Navigation.css";

const primary = [["/", "Overview"], ["/transactions", "Transactions"], ["/budgets", "Budgets"], ["/goals", "Goals"]];
const extra = [
  { name: "Planning", links: [["/reports", "Reports"], ["/forecast", "Forecast"], ["/chat", "AI Advisor"], ["/subscriptions", "Subscriptions"]] },
  { name: "Markets and shopping", links: [["/stocks", "Stock watchlist"], ["/portfolios", "Simulator"], ["/news", "News"],
    ["/promotions", "Deals"], ["/grocery", "Grocery basket"], ["/my-products", "My Products"], ["/receipts", "Receipt scanner"], ["/receipts/history", "Receipt history"]] },
];

function Navigation() {
  const isLoggedIn = useNotificationInbox().account !== null;
  const [open, setOpen] = useState(false);
  const id = useId();
  const menu = useRef(null);
  const trigger = useRef(null);

  useEffect(() => {
    if (!open) return;
    function closeOutside(event) {
      if (!menu.current?.contains(event.target)) setOpen(false);
    }
    function closeOnEscape(event) {
      if (event.key === "Escape" && menu.current?.contains(document.activeElement)) {
        setOpen(false);
        trigger.current?.focus();
      }
    }
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  return (
    <nav className="nav-container" aria-label="Main navigation">
      <Link to="/" className="brand" aria-label="FinDash home">
        <span className="brand-mark">F</span>
        <span>Fin<span>Dash</span></span>
      </Link>
      {isLoggedIn && <div className="nav-sections">
        <ul className="nav-primary-links">
          {primary.map(([path, label]) => <li key={path}><NavLink to={path} end={path === "/"}>{label}</NavLink></li>)}
        </ul>
        <div className="nav-disclosure" ref={menu} onBlur={(event) => {
          if (event.relatedTarget && !event.currentTarget.contains(event.relatedTarget)) setOpen(false);
        }}>
          <button ref={trigger} type="button" className="nav-menu-trigger" onClick={() => setOpen(!open)}
            aria-expanded={open} aria-controls={id}><span className="nav-more-label">More</span>
            <span className="nav-mobile-label">Menu</span> <FiChevronDown aria-hidden="true" /></button>
          <div id={id} className="nav-menu" hidden={!open}>
            <ul className="nav-menu-primary">{primary.map(([path, label]) => <li key={path}>
              <NavLink to={path} end={path === "/"} onClick={() => setOpen(false)}>{label}</NavLink>
            </li>)}</ul>
            {extra.map(({ name, links }) => <div key={name}>
              <p>{name}</p>
              <ul>{links.map(([path, label]) => <li key={path}>
                <NavLink to={path} end={path === "/receipts"} onClick={() => setOpen(false)}>{label}</NavLink>
              </li>)}</ul>
            </div>)}
          </div>
        </div>
      </div>}
      <div className="nav-actions">
        {isLoggedIn && <NotificationBell />}
        <ThemeToggle />
        {isLoggedIn ? <Link className="btn-nav btn-outline" to="/logout">Log out</Link> : <>
          <Link className="btn-nav btn-ghost" to="/login">Log in</Link>
          <Link className="btn-nav btn-primary" to="/register">Get started</Link>
        </>}
      </div>
    </nav>
  );
}

export default Navigation;
