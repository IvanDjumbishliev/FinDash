import ThemeToggle from "./ThemeToggle";
import NotificationBell from "./NotificationBell";
import { useNotificationInbox } from "./notificationContext";
import { NavLink, Link } from "react-router-dom";
import "../styles/components/Navigation.css";

function Navigation() {
  const isLoggedIn = useNotificationInbox().account !== null;

  return (
    <nav className="nav-container">
      <Link to="/" className="brand" aria-label="FinDash home">
        <span className="brand-mark">F</span>
        <span>Fin<span>Dash</span></span>
      </Link>
      {isLoggedIn && (
        <ul className="nav-links">
          <li><NavLink to="/" end>Overview</NavLink></li>
          <li><NavLink to="/transactions">Transactions</NavLink></li>
          <li><NavLink to="/budgets">Budgets</NavLink></li>
          <li><NavLink to="/goals">Goals</NavLink></li>
          <li><NavLink to="/reports">Reports</NavLink></li>
          <li><NavLink to="/forecast">Forecast</NavLink></li>
          <li><NavLink to="/chat">AI Advisor</NavLink></li>
          <li><NavLink to="/promotions">Deals</NavLink></li>
          <li><NavLink to="/grocery">Grocery basket</NavLink></li>
          <li><NavLink to="/stocks">Stock watchlist</NavLink></li>
          <li><NavLink to="/portfolios">Simulator</NavLink></li>
          <li><NavLink to="/news">News</NavLink></li>
          <li><NavLink to="/subscriptions">Subscriptions</NavLink></li>
        </ul>
      )}
      <div className="nav-actions">
        {isLoggedIn && <NotificationBell />}
        <ThemeToggle />
        {isLoggedIn ? (
          <Link className="btn-nav btn-outline" to="/logout">Log out</Link>
        ) : (
          <>
            <Link className="btn-nav btn-ghost" to="/login">Log in</Link>
            <Link className="btn-nav btn-primary" to="/register">Get started</Link>
          </>
        )}
      </div>
    </nav>
  );
}

export default Navigation;
