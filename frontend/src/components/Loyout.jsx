import { Suspense, useEffect, useRef, useSyncExternalStore } from "react";
import { Link, useLocation } from 'react-router-dom';
import { Outlet } from "react-router";
import Navigation from "./Navigation";
import PageBoundary from "./PageBoundary";
import { DashboardLoading } from "./DashboardFeedback";
import { NotificationProvider } from "./NotificationInbox";
import { notificationAccount } from "./notificationContext";
import "../styles/components/Notifications.css";
import { FaInstagram, FaDiscord, FaFacebook } from 'react-icons/fa';
import '../styles/components/Footer.css';

function subscribeToStorage(listener) {
    window.addEventListener("storage", listener);
    return () => window.removeEventListener("storage", listener);
}

export default function Footer() {
    const account = useSyncExternalStore(subscribeToStorage, notificationAccount);
    const { pathname } = useLocation();
    const previousPath = useRef(pathname);
    const main = useRef(null);

    useEffect(() => {
        if (previousPath.current !== pathname) {
            previousPath.current = pathname;
            main.current?.focus({ preventScroll: true });
        }
    }, [pathname]);

    return (
        <div className="fade-in">
            <a className="skip-to-content" href="#main-content">Skip to content</a>
            <NotificationProvider key={account} account={account}>
                <header className="header">
                    <Navigation />
                </header>
                <div id="main-content" tabIndex={-1} ref={main}>
                    <PageBoundary key={pathname} message="Could not load this page. Reload to try again.">
                        <Suspense fallback={<div className="dashboard-shell"><DashboardLoading label="Loading page" /></div>}>
                            <Outlet />
                        </Suspense>
                    </PageBoundary>
                </div>
            </NotificationProvider>
            <footer className="footer">
                <div className="footer-content">
                    <div className="footer-section">
                        <h4>FinDash</h4>
                        <p>Your money, clearly understood. Track spending, discover insights, and stay ahead.</p>
                    </div>
                    <div className="footer-section">
                        <h4>Quick Links</h4>
                        <div className="footer-links">
                            <Link to="/" className="footer-btn">Home</Link>
                            <Link to="/transactions" className="footer-btn">Transactions</Link>
                            <Link to="/chat" className="footer-btn">Chat</Link>
                            <Link to="/promotions" className="footer-btn">Promotions</Link>
                            <Link to="/stocks" className="footer-btn">Stocks</Link>
                            <Link to="/news" className="footer-btn">News</Link>
                        </div>
                    </div>
                    <div className="footer-section">
                        <h4>Contact</h4>
                        <div className="social-links">
                            <a href="https://instagram.com" target="_blank" rel="noopener noreferrer">
                                <FaInstagram className="social-icon" />
                            </a>
                            <a href="https://discord.gg" target="_blank" rel="noopener noreferrer">
                                <FaDiscord className="social-icon" />
                            </a>
                            <a href="https://facebook.com" target="_blank" rel="noopener noreferrer">
                                <FaFacebook className="social-icon" />
                            </a>
                        </div>
                    </div>
                </div>
                <div className="footer-bottom">
                    <p>&copy; {new Date().getFullYear()} FinDash. Built for smarter decisions.</p>
                </div>
            </footer>
        </div>
    );
}