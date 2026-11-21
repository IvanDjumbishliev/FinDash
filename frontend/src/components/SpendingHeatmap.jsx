import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import PropTypes from "prop-types";
import api from "../api";
import { calendarDate, intensity, nextCellIndex, spendingBands, summarizeHeatmap } from "../spendingHeatmap";
import "../styles/components/SpendingHeatmap.css";

const endpoint = "/api/analytics/spending-heatmap/";
const dateLabel = new Intl.DateTimeFormat(undefined, { dateStyle: "full", timeZone: "UTC" });
const monthLabel = new Intl.DateTimeFormat(undefined, { month: "short", timeZone: "UTC" });
const months = Array.from({ length: 12 }, (_, index) => monthLabel.format(new Date(Date.UTC(2024, index, 1))));
const weekdayLabels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function useHeatmapRequest(url, params, revision, retry) {
  const [response, setResponse] = useState(null);
  useEffect(() => {
    if (!params) return;
    const controller = new AbortController();
    api.get(url, { params, signal: controller.signal }).then(
      ({ data }) => {
        if (!controller.signal.aborted) setResponse({ params, revision, retry, data });
      },
      () => {
        if (!controller.signal.aborted) setResponse({ params, revision, retry, error: true });
      },
    );
    return () => controller.abort();
  }, [url, params, revision, retry]);
  return response?.params === params && response.revision === revision && response.retry === retry ? response : null;
}

export default function SpendingHeatmap({ revision }) {
  const [year, setYear] = useState(() => new Date().getFullYear());
  const [yearInput, setYearInput] = useState(year);
  const [category, setCategory] = useState("");
  const [selected, setSelected] = useState(null);
  const [focusIndex, setFocusIndex] = useState(0);
  const [tooltip, setTooltip] = useState(null);
  const [yearRetry, setYearRetry] = useState(0);
  const [dayRetry, setDayRetry] = useState(0);
  const buttons = useRef([]);
  const range = useMemo(() => {
    const value = String(year).padStart(4, "0");
    return { start: `${value}-01-01`, end: `${value}-12-31` };
  }, [year]);
  const yearly = useHeatmapRequest(endpoint, range, revision, yearRetry);
  const data = yearly?.data;
  const detailParams = useMemo(() => selected && data ? {
    date: selected,
    currency: data.currency,
    ...(category ? { category } : {}),
  } : null, [selected, data, category]);
  const daily = useHeatmapRequest(`${endpoint}day/`, detailParams, revision, dayRetry);

  const allDays = useMemo(() => data?.days ?? [], [data]);
  const categories = useMemo(() => Array.from(new Set(allDays.flatMap((day) =>
    Object.keys(day.category_totals)))).sort(), [allDays]);
  const { cells, months: totals, peak, hasActivity } = useMemo(() =>
    summarizeHeatmap(allDays, category), [allDays, category]);
  const formatter = useMemo(() => new Intl.NumberFormat(undefined, {
    style: "currency", currency: data?.currency ?? "USD",
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  }), [data?.currency]);

  const money = (cents) => formatter.format(cents / 100);
  const dayLabel = (value) => dateLabel.format(calendarDate(value));
  const describe = (cell) => `${dayLabel(cell.date)} · ${money(cell.cents)} net spending · ${cell.count} ${cell.count === 1 ? "transaction" : "transactions"}`;

  function submitYear(event) {
    event.preventDefault();
    const value = Number(yearInput);
    if (!Number.isInteger(value) || value < 2 || value > 9998 || value === year) return;
    setYear(value);
    setCategory("");
    setSelected(null);
    setFocusIndex(0);
    setTooltip(null);
  }

  function showTooltip(event, cell) {
    const bounds = event.currentTarget.getBoundingClientRect();
    setTooltip({
      text: describe(cell),
      x: Math.max(8, Math.min(bounds.left, window.innerWidth - 280)),
      y: bounds.top,
    });
  }

  function navigate(event, index, cell) {
    if (event.key === "Escape") setTooltip(null);
    const next = nextCellIndex(event.key, index, cell.weekday, cells.length);
    if (next === null) return;
    event.preventDefault();
    buttons.current[next]?.focus();
  }

  return (
    <section className="dashboard-card spending-heatmap" aria-labelledby="spending-heatmap-title">
      <header className="heatmap-header">
        <div>
          <h2 id="spending-heatmap-title">Financial activity</h2>
          <p>Daily net spending{data ? ` in ${data.currency} · ${data.timezone}` : ""}</p>
        </div>
        <div className="heatmap-controls">
          <form onSubmit={submitYear}>
            <label htmlFor="heatmap-year">Year</label>
            <div className="heatmap-year-input">
              <input id="heatmap-year" type="number" min="2" max="9998" required
                value={yearInput} onChange={(event) => setYearInput(event.target.value)} />
              <button type="submit">Go</button>
            </div>
          </form>
          <label>
            Category
            <select value={category} disabled={!categories.length} onChange={(event) => {
              setCategory(event.target.value);
              setTooltip(null);
            }}>
              <option value="">All categories</option>
              {category && !categories.includes(category) && <option value={category}>{category}</option>}
              {categories.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
          </label>
        </div>
      </header>
      {!yearly && <p className="heatmap-state" role="status">Loading spending for {year}…</p>}
      {yearly?.error && <div className="heatmap-state" role="alert">
        Couldn’t load the spending calendar.{" "}
        <button onClick={() => setYearRetry((value) => value + 1)}>Try again</button>
      </div>}
      {data && <>
        <p className="heatmap-instructions" id="heatmap-instructions">
          Select a day to see its transactions. Use arrow keys to move, or swipe to see more months.
        </p>
        <div className="heatmap-scroll" onScroll={() => setTooltip(null)}>
          <div className="heatmap-calendar" role="group" aria-label={`Daily spending in ${year}`}
            aria-describedby="heatmap-instructions"
            style={{ "--weeks": (cells.at(-1)?.week ?? 0) + 1 }}>
            {cells.filter((cell) => cell.date.endsWith("-01")).map((cell) =>
              <span key={cell.month} className="heatmap-month" aria-hidden="true"
                style={{ gridColumn: `${cell.week + 2} / span 3` }}>{months[cell.month]}</span>
            )}
            {weekdayLabels.map((label, index) =>
              <span key={label} className="heatmap-weekday" aria-hidden="true"
                style={{ gridRow: index + 2 }}>{index % 2 === 1 ? label : ""}</span>
            )}
            {cells.map((cell, index) =>
              <button key={cell.date} type="button" className="heatmap-cell"
                ref={(element) => { buttons.current[index] = element; }}
                style={{ gridColumn: cell.week + 2, gridRow: cell.weekday + 2 }}
                data-level={intensity(cell.cents, peak?.cents ?? 0)}
                data-offset={cell.count > 0 && cell.cents <= 0}
                aria-label={describe(cell)} aria-pressed={selected === cell.date}
                tabIndex={focusIndex === index ? 0 : -1}
                onMouseEnter={(event) => showTooltip(event, cell)} onMouseLeave={() => setTooltip(null)}
                onFocus={(event) => { setFocusIndex(index); showTooltip(event, cell); }}
                onBlur={() => setTooltip(null)}
                onKeyDown={(event) => navigate(event, index, cell)}
                onClick={() => { setFocusIndex(index); setSelected(cell.date); setTooltip(null); }} />
            )}
          </div>
        </div>
        {tooltip && createPortal(
          <div className="heatmap-tooltip" aria-hidden="true" style={{ left: tooltip.x, top: tooltip.y }}>
            {tooltip.text}
          </div>, document.body
        )}
        <ul className="heatmap-legend" aria-label="Spending intensity legend">
          <li><span className="heatmap-swatch" data-level="0" /> No activity</li>
          <li><span className="heatmap-swatch" data-level="0" data-offset="true" /> Zero or negative net spending</li>
          {spendingBands(peak?.cents ?? 0).map(({ level, min, max }) =>
            <li key={level}><span className="heatmap-swatch" data-level={level} />
              {min === max ? money(min) : `${money(min)}–${money(max)}`}
            </li>
          )}
        </ul>
        <p className="heatmap-instructions">Each darker band covers another quarter of the highest daily net spend in this view.</p>
        <div className="heatmap-peak">
          <h3>Most expensive day</h3>
          {peak ? <button type="button" onClick={() => setSelected(peak.date)}>
            {dayLabel(peak.date)} · {money(peak.cents)}
          </button> : <p>{hasActivity ? "No day had positive net spending." : "No spending activity for this selection."}</p>}
        </div>
        {selected && <div className="heatmap-details" aria-labelledby="heatmap-selected-date">
          <h3 id="heatmap-selected-date">{dayLabel(selected)}</h3>
          <div aria-live="polite" aria-atomic="true">
            {!daily && <p>Loading transactions…</p>}
            {daily?.error && <p>Couldn’t load these transactions.{" "}
              <button onClick={() => setDayRetry((value) => value + 1)}>Try again</button>
            </p>}
            {daily?.data && <p>{daily.data.transactions.length} matching {daily.data.transactions.length === 1 ? "transaction" : "transactions"}</p>}
          </div>
          {daily?.data?.transactions.length > 0 && <ul className="heatmap-transactions">
            {daily.data.transactions.map((item) => <li key={item.id}>
              <span>{item.description || item.category}<small>{item.category}{Number(item.spending) < 0 ? " · Refund" : ""}</small></span>
              <strong>{money(Math.round(Number(item.spending) * 100))}</strong>
            </li>)}
          </ul>}
        </div>}
        <div className="heatmap-monthly">
          <h3>Monthly net spending</h3>
          <dl>{months.map((month, index) => <div key={month}>
            <dt>{month}</dt><dd>{money(totals[index])}</dd>
          </div>)}</dl>
        </div>
      </>}
    </section>
  );
}

SpendingHeatmap.propTypes = { revision: PropTypes.number.isRequired };
