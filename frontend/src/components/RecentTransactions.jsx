import "../styles/components/RecentTransactions.css";
import { useEffect, useState } from "react";
import PropTypes from "prop-types";
import api from "../api";

const fetchLatestTransactions = async (limit) => {
  try {
    const response = await api.get("/api/transactions/", {
      params: { limit, ordering: "-timestamp" },
    });

    return response.data.results;
  } catch (error) {
    alert("Failed to fetch transactions.");
    return [];
  }
};

export default function RecentTransactions({ limit }) {
  const [LastTransactions, setLastTransactions] = useState([]);

  useEffect(() => {
    const fetchTransactions = async () => {
      const transactions = await fetchLatestTransactions(limit);
      setLastTransactions(transactions);
    };

    fetchTransactions();
  }, [limit]);

  if (!LastTransactions || LastTransactions.length === 0) {
    return (
      <div className="transactions-wrapper">
        <p className="text-center">
          No transactions found. Add some transactions to see them here.
        </p>
      </div>
    );
  }

  return (
    <table className="transactions-table">
      <thead>
        <tr>
          <th>#</th>
          <th>Category</th>
          <th>Amount</th>
          <th>Date</th>
        </tr>
      </thead>
      <tbody>
        {[...LastTransactions]
          .sort((a, b) => new Date(b.date) - new Date(a.date))
          .map((transaction, index) => (
            <tr
              key={index}
              className={transaction.amount > 0 ? "income" : "expense"}
            >
              <td>{index + 1}</td>
              <td>{transaction.category}</td>
              <td>
                {new Intl.NumberFormat("en-US", {
                  style: "currency",
                  currency: transaction.currency,
                }).format(transaction.amount)}
              </td>
              <td>{new Date(transaction.timestamp).toDateString()}</td>
            </tr>
          ))}
      </tbody>
    </table>
  );
}

RecentTransactions.propTypes = { limit: PropTypes.number.isRequired };
