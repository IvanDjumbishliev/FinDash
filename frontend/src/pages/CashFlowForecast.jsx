import { useEffect, useState } from "react";
import { FiActivity, FiCalendar, FiInfo, FiRepeat } from "react-icons/fi";
import api from "../api";
import ForecastScenarios from "../components/ForecastScenarios";
import { CashFlowComparison, ForecastTrajectory } from "../components/CashFlowCharts";
import { balanceInput, forecastMetrics, horizons, recurringPayments } from "../cashFlowForecast";
import { displayDate, displayRange, money } from "../copilotPresentation";
import "../styles/pages/CashFlowForecast.css";

const endpoint = "/api/forecast/cash-flow/";
const paymentPageSize = 8;

export default function CashFlowForecast() {
  const [horizon, setHorizon] = useState(30);
  const [draft, setDraft] = useState("");
  const [balance, setBalance] = useState("");
  const [inputError, setInputError] = useState("");
  const [request, setRequest] = useState(null);
  const [retry, setRetry] = useState(0);
  const [limit, setLimit] = useState(paymentPageSize);
  const requestKey = `${horizon}:${balance}:${retry}`;
  const result = request?.key === requestKey ? request : null;
  const data = result?.data;

  useEffect(() => {
    const controller = new AbortController();
    api.get(endpoint, {
      params: { horizon },
      ...(balance ? { headers: { "X-Starting-Balance": balance } } : {}),
      signal: controller.signal,
    }).then(({ data: forecast }) => {
      if (!controller.signal.aborted) setRequest({ key: requestKey, data: forecast });
    }).catch((error) => {
      if (!controller.signal.aborted) setRequest({
        key: requestKey,
        error: error.response?.data?.starting_balance?.[0] || error.response?.data?.error ||
          "Couldn’t load your forecast. Try again.",
      });
    });
    return () => controller.abort();
  }, [horizon, balance, requestKey]);

  function applyBalance(event) {
    event.preventDefault();
    const parsed = balanceInput(draft);
    setInputError(parsed.error || "");
    if (!parsed.error) setBalance(parsed.value);
  }

  const payments = data ? recurringPayments(data.recurring) : [];
  return <main className="forecast-page">
    <header className="forecast-heading">
      <span><FiActivity aria-hidden="true" /></span>
      <div><h1>Cash flow forecast</h1><p>See what may come in, what may go out, and how your balance could change.</p></div>
      <a className="forecast-scenario-jump" href="#forecast-scenarios-title">What-if scenarios</a>
    </header>

    <section className="forecast-panel forecast-controls" aria-label="Forecast options">
      <fieldset>
        <legend>Forecast horizon</legend>
        <div className="forecast-horizons">
          {horizons.map((days) => <label key={days}>
            <input type="radio" name="forecast-horizon" value={days} checked={horizon === days}
              onChange={() => { setHorizon(days); setLimit(paymentPageSize); }} />
            <span>{days} days</span>
          </label>)}
        </div>
      </fieldset>
      <form onSubmit={applyBalance} noValidate>
        <label htmlFor="forecast-balance">Starting balance {data && <span>({data.currency})</span>}</label>
        <div className="forecast-balance-entry">
          <input id="forecast-balance" type="text" inputMode="decimal" maxLength={16} placeholder="Optional"
            value={draft} aria-describedby={inputError ? "forecast-balance-help forecast-balance-error" : "forecast-balance-help"}
            aria-invalid={Boolean(inputError)} onChange={(event) => { setDraft(event.target.value); setInputError(""); }} />
          <button type="submit" className="forecast-primary">Apply balance</button>
          {balance && <button type="button" onClick={() => { setDraft(""); setBalance(""); setInputError(""); }}>Remove</button>}
        </div>
        <p id="forecast-balance-help" className="forecast-muted">Use your expected balance at the end of today.</p>
        {inputError && <p id="forecast-balance-error" className="forecast-error" role="alert">{inputError}</p>}
      </form>
    </section>

    {!result && <p className="forecast-panel forecast-status" role="status">Loading your cash flow forecast…</p>}
    {result?.error && <section className="forecast-panel forecast-failure" role="alert">
      <p>{result.error}</p><button type="button" onClick={() => setRetry((value) => value + 1)}>Try again</button>
    </section>}

    {data && <div className="forecast-results">
      <p className="forecast-period"><FiCalendar aria-hidden="true" /> {displayRange(data.start_date, data.end_date)} · {data.currency} · {data.timezone}</p>
      {data.status === "insufficient_history" && <section className="forecast-insufficient" aria-label="Insufficient data">
        <FiInfo aria-hidden="true" /><div><h2>More history is needed for a full forecast</h2>
          <p>Scheduled recurring flows are shown when available. Variable income, expenses, and the full balance estimate need more recorded weeks.</p></div>
      </section>}
      <dl className="forecast-kpis">
        {forecastMetrics(data).map(({ label, value, detail }) => <div key={label}>
          <dt>{label}</dt>
          <dd>{value == null ? "Unavailable" : money(value, data.currency)}</dd>
          <dd>{detail === data.end_date ? displayDate(detail) : detail}</dd>
        </div>)}
      </dl>

      <CashFlowComparison data={data} />
      <ForecastTrajectory data={data} />

      <section className="forecast-panel forecast-payments" aria-labelledby="forecast-payments-title">
        <h2 id="forecast-payments-title"><FiRepeat aria-hidden="true" /> Upcoming recurring payments</h2>
        <p className="forecast-muted">Expected deposits and charges during this forecast. Dates and amounts are estimates.</p>
        {payments.length ? <>
          <ul>{payments.slice(0, limit).map((payment) => <li key={payment.key}>
            <div><strong>{payment.label || "Recurring payment"}</strong>
              <small>{displayDate(payment.date)} · {payment.frequency} · {payment.source === "confirmed_subscription" ? "Confirmed subscription" : "Detected from history"}</small>
            </div>
            <span className={`forecast-payment-${payment.kind}`}>{payment.kind === "income" ? "Income" : "Expense"} {money(payment.amount, data.currency)}</span>
          </li>)}</ul>
          {payments.length > limit && <button type="button" onClick={() => setLimit((value) => value + paymentPageSize)}>
            Show more payments ({payments.length - limit} left)
          </button>}
        </> : <p>No recurring deposits or charges are expected in this horizon.</p>}
      </section>

      <details className="forecast-panel forecast-assumptions">
        <summary>Forecast assumptions and data coverage</summary>
        <p className="forecast-muted">
          {data.history.transaction_count} qualifying transactions across {data.history.active_days} recorded days.
          {" "}{data.history.baseline.complete_weeks} complete weeks available for the variable estimate.
        </p>
        <h3>Assumptions</h3><ul>{data.assumptions.map((item) => <li key={item}>{item}</li>)}</ul>
        <h3>Limitations</h3><ul>{data.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
      </details>
    </div>}
    <ForecastScenarios data={data} onHorizonChange={setHorizon} />
  </main>;
}
