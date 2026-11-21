import { useState, useEffect } from "react";
import api from "../api";
import "../styles/pages/Home.css";
import RecentTransactions from "../components/RecentTransactions";
import PieChart from "../components/PieChart";
import Summary from "../components/Summary";
import PDF_enter from "../components/PDFEnter";

function Home() {
  const [transactionStats, setTransactionStats] = useState([]);
  const [user, setUser] = useState(null);
  const [importRevision, setImportRevision] = useState(0);

  const fetchTransactionStats = async () => {
    try {
      const response = await api.get("/api/transaction-stats/");
      if (response.status === 200) {
        setTransactionStats(response.data);
      } else {
        alert("Failed to fetch transaction stats.");
      }
    } catch (error) {
      console.error("Error fetching transaction stats:", error);
    }
  };

  const fetchUserData = async () => {
    try {
      const response = await api.get("/api/user/profile");
      if (response.status === 200) {
        setUser(response.data);
      }
    } catch (error) {
      console.log("Error trying to fetch user data: ", error);
    }
  };

  useEffect(() => {
    fetchTransactionStats();
    fetchUserData();
  }, []);

  return (
    <main className="dashboard-shell">
      <section className="dashboard-hero">
        <div>
          <p className="eyebrow">Financial overview</p>
          <h1>{user ? `Welcome back, ${user}` : "Welcome to FinDash"}</h1>
          <p>See the full picture, understand your habits, and make your next money move with confidence.</p>
        </div>
        <PDF_enter onImported={() => {
          fetchTransactionStats();
          setImportRevision((value) => value + 1);
        }} />
      </section>
      <section className="dashboard-card">
        <div className="grid">
          <PieChart transactions={transactionStats} />
          <div className="transactions-wrapper">
            <h2>Recent activity</h2>
            <RecentTransactions key={importRevision} limit={10} />
          </div>
        </div>
      </section>
      <Summary />
    </main>
  );
}

export default Home;
