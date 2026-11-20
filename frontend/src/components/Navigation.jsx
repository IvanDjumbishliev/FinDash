import ThemeToggle from "./ThemeToggle";
import { NavLink, Link } from "react-router-dom";
import { ACCESS_TOKEN } from "../constants";
import "../styles/components/Navigation.css";

function Navigation() {
  const isLoggedIn = Boolean(localStorage.getItem(ACCESS_TOKEN));

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
          <li><NavLink to="/chat">AI Advisor</NavLink></li>
          <li><NavLink to="/promotions">Deals</NavLink></li>
          <li><NavLink to="/stocks">Stock watchlist</NavLink></li>
        </ul>
      )}
      <div className="nav-actions">
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
