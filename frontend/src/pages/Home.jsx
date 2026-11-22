import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { FiActivity, FiSliders } from "react-icons/fi";
import api from "../api";
import PDF_enter from "../components/PDFEnter";
import { useNotificationInbox } from "../components/notificationContext";
import { DashboardDataCard, DashboardError, DashboardLiveCard, DashboardLoading } from "../components/DashboardWidgets";
import { dashboardSections, defaultWidgets, readWidgets, saveWidgets, widgets } from "../dashboard";
import "../styles/pages/Home.css";

const SpendingHeatmap = lazy(() => import("../components/SpendingHeatmap"));

export default function Home() {
  const { account } = useNotificationInbox();
  const [visible, setVisible] = useState(() => readWidgets(localStorage, account));
  const [revision, setRevision] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState(null);
  const [notice, setNotice] = useState("");
  const preferences = useRef(null);
  const sections = dashboardSections(visible);
  const key = `${sections}:${revision}:${attempt}`;

  useEffect(() => {
    if (!sections) return;
    const controller = new AbortController();
    api.get("/api/dashboard/", { params: { sections }, signal: controller.signal, timeout: 12_000 }).then(({ data }) => {
      if (!controller.signal.aborted) setResult({ key, data });
    }).catch(() => {
      if (!controller.signal.aborted) setResult({ key, failed: true });
    });
    return () => controller.abort();
  }, [sections, key]);

  function apply(next) {
    setVisible(next);
    try {
      saveWidgets(localStorage, account, next);
      setNotice("Dashboard preferences saved.");
    } catch {
      setNotice("Dashboard updated. This browser could not save your preferences.");
    }
    preferences.current.close();
  }

  const current = result?.key === key ? result : null;

  return <main className="dashboard-shell dash-home">
    <header className="dash-hero">
      <div>
        <span className="dash-hero-icon"><FiActivity aria-hidden="true" /> Overview</span>
        <h1>{current?.data?.username ? `Welcome back, ${current.data.username}` : "Your financial dashboard"}</h1>
        <p>Track recorded activity and see what’s ahead.</p>
      </div>
      <div className="dash-actions">
        <button className="dash-button" onClick={() => { setNotice(""); preferences.current.showModal(); }}>
          <FiSliders aria-hidden="true" /> Customize dashboard
        </button>
        <PDF_enter onImported={() => {
          setNotice("Statement imported. Your dashboard is updating.");
          setRevision((value) => value + 1);
        }} />
      </div>
    </header>

    <dialog ref={preferences} className="dash-dialog" aria-labelledby="widget-preferences"
      onClose={(event) => event.currentTarget.querySelector("form").reset()}>
      <form onSubmit={(event) => {
        event.preventDefault();
        apply(new FormData(event.currentTarget).getAll("widget"));
      }}>
        <h2 id="widget-preferences">Customize dashboard</h2>
        <p className="dash-note">Choose which widgets appear on this browser for your account.</p>
        <fieldset key={visible.join(",")} className="dash-checkboxes">
          <legend className="dash-sr-only">Dashboard widgets</legend>
          {widgets.map(({ id, label }) => <label key={id}>
            <input type="checkbox" name="widget" value={id} defaultChecked={visible.includes(id)} /> {label}
          </label>)}
        </fieldset>
        <div className="dash-actions">
          <button className="dash-button" type="button" onClick={() => apply(defaultWidgets)}>Reset defaults</button>
          <button className="dash-button" type="button" onClick={() => {
            preferences.current.querySelector("form").reset();
            preferences.current.close();
          }}>Cancel</button>
          <button className="dash-button dash-primary" type="submit">Save layout</button>
        </div>
      </form>
    </dialog>
    <p className="dash-notice" role="status">{notice}</p>
    {!visible.length && <p className="dash-empty dash-panel">Your dashboard is empty. Choose widgets to make it yours.</p>}
    <div className="dash-grid">
      {sections && !current && <div className="dash-panel dash-wide"><DashboardLoading /></div>}
      {sections && current?.failed && <div className="dash-panel dash-wide">
        <DashboardError onRetry={() => setAttempt((value) => value + 1)}>Could not load the dashboard summaries.</DashboardError>
      </div>}
      {widgets.filter(({ id }) => visible.includes(id)).map(({ id, separate }) => {
        if (id === "heatmap") return <div className="dash-wide dash-heatmap" key={id}>
          <Suspense fallback={<DashboardLoading label="Loading spending heatmap" />}>
            <SpendingHeatmap revision={revision} />
          </Suspense>
        </div>;
        if (separate) return <DashboardLiveCard key={id} type={id} revision={revision} />;
        return current?.data && <DashboardDataCard key={id} type={id} data={current.data} />;
      })}
    </div>
  </main>;
}
