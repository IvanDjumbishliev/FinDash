import PropTypes from "prop-types";
import { useState } from "react";
import api from "../api";
import "../styles/components/TransactionForm.css";

function TransactionForm({ onTransactionAdded }) {
  const [amount, setAmount] = useState("");
  const [category, setCategory] = useState("business services");
  const [currency, setCurrency] = useState("BGN");
  const [description, setDescription] = useState("");

  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState(null);

  async function handleSubmit(event) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setFeedback(null);
    try {
      await api.post("/api/transactions/", {
        amount, category, currency, particulars: description,
      }, { timeout: 12_000 });
      setAmount("");
      setCategory("business services");
      setCurrency("BGN");
      setDescription("");
      setFeedback({ message: "Transaction recorded." });
      onTransactionAdded();
    } catch (error) {
      const data = error.response?.data;
      const details = data && typeof data === "object"
        ? Object.values(data).flat().find((value) => typeof value === "string")
        : null;
      setFeedback({ error: true, message: details || "Could not record the transaction. Check the details and try again." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="transaction-form">
      <h1>Transaction Form</h1>
      <form onSubmit={handleSubmit}>
        <label htmlFor="amount">Amount</label>
        <input
          type="number"
          id="amount"
          name="amount"
          step="0.01"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          required
        />

        <label htmlFor="category">Category</label>
        <select
          id="category"
          name="category"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          required
        >
          <option value="business services">Business Services</option>
          <option value="shopping">Shopping</option>
          <option value="entertainment">Entertainment</option>
          <option value="groceries">Groceries</option>
          <option value="eating out">Eating Out</option>
          <option value="bills">Bills</option>
          <option value="transport">Transport</option>
          <option value="health">Health</option>
          <option value="travel">Travel</option>
          <option value="finance">Finance</option>
          <option value="general">General</option>
        </select>

        <label htmlFor="currency">Currency</label>
        <select
          id="currency"
          name="currency"
          value={currency}
          onChange={(e) => setCurrency(e.target.value)}
          required
        >
          <option value="BGN">BGN</option>
          <option value="EUR">EUR</option>
          <option value="USD">USD</option>
        </select>

        <label htmlFor="description">Description</label>
        <textarea
          id="description"
          name="description"
          rows="3"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        ></textarea>

        {feedback && <p className={feedback.error ? "dash-error" : "dash-notice"} role={feedback.error ? "alert" : "status"}>
          {feedback.message}
        </p>}
        <button type="submit" className="invisi-btn" disabled={busy}>
          {busy ? "Saving…" : "Submit"}
        </button>
      </form>
    </div>
  );
}

export default TransactionForm;

TransactionForm.propTypes = {
  onTransactionAdded: PropTypes.func.isRequired,
};
