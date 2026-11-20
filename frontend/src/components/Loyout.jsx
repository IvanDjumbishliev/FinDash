import React from 'react';
import { Link } from 'react-router-dom';
import { Outlet } from "react-router";
import Navigation from "./Navigation";
import { FaInstagram, FaDiscord, FaFacebook } from 'react-icons/fa';
import '../styles/components/Footer.css';

export default function Footer() {
    return (
        <div className="fade-in">
            <header className="header">
                <Navigation />
            </header>
            <Outlet />
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