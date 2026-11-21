import { useEffect, useRef, useState } from "react";
import {
  FiArrowRight, FiArrowUp, FiBarChart2, FiCalendar, FiClock, FiGitPullRequest,
  FiMessageSquare, FiRepeat, FiShield, FiTrash2, FiZap,
} from "react-icons/fi";
import CopilotResponse from "../components/CopilotResponse";
import { followUpQuestions, suggestedQuestions } from "../copilotPresentation";
import api from "../api";
import "../styles/pages/Chat.css";

const chat = "/api/chat/";
const questionIcons = {
  spending: FiBarChart2, compare: FiGitPullRequest, budgets: FiCalendar, subscriptions: FiRepeat,
};

function errorText(error) {
  const body = error.response?.data;
  if (body?.error) return body.error;
  if (error.response?.status === 429) return "Too many requests. Wait a moment and try again.";
  return "The Copilot request failed. Please try again.";
}

export default function Chat() {
  const [settings, setSettings] = useState(null);
  const [turns, setTurns] = useState([]);
  const [token, setToken] = useState(null);
  const [prompt, setPrompt] = useState("");
  const [consent, setConsent] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [pending, setPending] = useState("");
  const [status, setStatus] = useState("");
  const input = useRef(null);
  const form = useRef(null);
  const tail = useRef(null);
  const turnElements = useRef(new Map());
  const turnId = useRef(0);
  const scrollToLatest = useRef(false);

  useEffect(() => {
    if (!scrollToLatest.current) return;
    if (pending) {
      tail.current?.scrollIntoView({ block: "nearest" });
    } else {
      turnElements.current.get(turns.length - 1)?.scrollIntoView({ block: "start" });
      scrollToLatest.current = false;
    }
  }, [turns, pending]);

  useEffect(() => {
    const controller = new AbortController();
    const options = { signal: controller.signal };
    Promise.all([api.get(`${chat}settings/`, options), api.get(`${chat}history/`, options)])
      .then(([preferences, history]) => {
        setSettings(preferences.data);
        setTurns(history.data.turns.map((turn) => ({ ...turn, id: ++turnId.current })));
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(errorText(failure));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [revision]);

  async function updateSetting(key, value) {
    if (key === "history_enabled" && !value && turns.length &&
        !window.confirm("Turn off history and delete your saved Copilot conversation?")) return;
    setBusy("settings");
    setError("");
    setStatus("");
    try {
      const { data } = await api.patch(`${chat}settings/`, { [key]: value });
      setSettings(data);
      setToken(null);
      if (key === "history_enabled" || !data.history_enabled) setTurns([]);
      if (!data.sharing_enabled) setConsent(false);
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setBusy("");
    }
  }

  async function clearConversation() {
    if (settings.history_enabled && !window.confirm("Delete your saved Copilot conversation?")) return;
    setBusy("delete");
    setError("");
    setStatus("");
    try {
      await api.delete(`${chat}history/`);
      setToken(null);
      setTurns([]);
      setStatus(settings.history_enabled ? "Saved conversation deleted." : "Conversation cleared.");
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setBusy("");
    }
  }

  async function ask(event) {
    event.preventDefault();
    const question = prompt.trim();
    if (!question || !consent || !settings?.sharing_enabled || busy) return;
    scrollToLatest.current = true;
    setPending(question);
    setBusy("answer");
    setError("");
    setStatus("");
    try {
      const { data } = await api.post(chat, {
        prompt: question,
        consent,
        ...(token ? { context_token: token } : {}),
      });
      const { context_token: nextToken, ...response } = data;
      setToken(nextToken);
      const nextTurn = { id: ++turnId.current, prompt: question, response };
      setTurns((previous) => [...previous, nextTurn].slice(-24));
      setPrompt("");
    } catch (failure) {
      setError(errorText(failure));
      if (["stale_context", "sharing_disabled"].includes(failure.response?.data?.code)) {
        setToken(null);
        setTurns([]);
        setLoading(true);
        setRevision((value) => value + 1);
      }
    } finally {
      setPending("");
      setBusy("");
    }
  }

  function fillQuestion(question) {
    setPrompt(question);
    setError("");
    input.current?.focus();
  }

  function openTurn(index) {
    setSidebarOpen(false);
    const turn = turnElements.current.get(index);
    turn?.scrollIntoView({ block: "start" });
    turn?.focus({ preventScroll: true });
  }

  function refresh() {
    setError("");
    setLoading(true);
    setRevision((value) => value + 1);
  }

  const active = Boolean(settings?.sharing_enabled) && !loading;
  const canSend = active && !busy && consent && Boolean(prompt.trim());
  const latest = turns.at(-1)?.response;

  return (
    <main className="copilot-page">
      <header className="copilot-heading">
        <div className="copilot-heading-mark"><FiZap aria-hidden="true" /></div>
        <div>
          <h1>Financial Copilot</h1>
          <p>Ask about your spending, budgets, and subscriptions.</p>
        </div>
      </header>

      {loading && !settings && <div className="copilot-loading" role="status">
        <span className="copilot-spinner" aria-hidden="true" /> Loading Copilot…
      </div>}
      {!settings && !loading && <div className="copilot-error" role="alert">
        <p>{error || "Copilot couldn’t load your settings."}</p>
        <button type="button" className="copilot-text-button" onClick={refresh}>Try again</button>
      </div>}

      {settings && <div className="copilot-workspace">
        <button type="button" className="copilot-mobile-panel" aria-expanded={sidebarOpen}
          aria-controls="copilot-sidebar" onClick={() => setSidebarOpen((value) => !value)}>
          <FiClock aria-hidden="true" /> History &amp; privacy <span>{sidebarOpen ? "Hide" : "Show"}</span>
        </button>
        <aside id="copilot-sidebar" className="copilot-sidebar" data-open={sidebarOpen}>
          <div className="copilot-history">
            <div className="copilot-sidebar-title">
              <FiClock aria-hidden="true" /><h2>{settings.history_enabled ? "Conversation history" : "This conversation"}</h2>
            </div>
            <p className="copilot-sidebar-note">
              {settings.history_enabled ? "Saved to your account" : "Only in this tab"}
            </p>
            {turns.length > 0
              ? <nav aria-label="Conversation turns">
                <ol>
                  {turns.map(({ id, prompt: question }, index) => ({ id, question, index })).reverse().map(({ id, question, index }) =>
                    <li key={id}><button type="button" onClick={() => openTurn(index)}>
                      <FiMessageSquare aria-hidden="true" /><span>{question}</span>
                    </button></li>
                  )}
                </ol>
              </nav>
              : <p className="copilot-history-empty">Your questions will appear here.</p>}
            <button type="button" className="copilot-text-button copilot-clear" onClick={clearConversation}
              disabled={Boolean(busy) || loading || !turns.length}>
              <FiTrash2 aria-hidden="true" /> {settings.history_enabled ? "Delete saved history" : "Clear conversation"}
            </button>
            <p className="copilot-sidebar-status" role="status">{status}</p>
          </div>

          <details className="copilot-privacy">
            <summary><FiShield aria-hidden="true" /> Privacy settings</summary>
            <fieldset className="copilot-settings" disabled={Boolean(busy) || loading}>
              <legend className="copilot-sr-only">Privacy settings</legend>
              <label><input type="checkbox" checked={settings.sharing_enabled}
                onChange={(event) => updateSetting("sharing_enabled", event.target.checked)} /> Allow sharing with Gemini</label>
              <label><input type="checkbox" checked={settings.history_enabled}
                onChange={(event) => updateSetting("history_enabled", event.target.checked)} /> Save conversation history</label>
              <p>{settings.history_enabled ? "Turning history off deletes the saved conversation." : "Your questions and answers stay in this tab unless you turn on history."}</p>
            </fieldset>
          </details>
        </aside>

        <section className="copilot-main" aria-label="Financial conversation">
          {turns.length === 0 && !pending && <div className="copilot-welcome">
            <span className="copilot-welcome-icon"><FiMessageSquare aria-hidden="true" /></span>
            <h2>What would you like to understand?</h2>
            <p>Start with a question about the financial activity recorded in FinDash.</p>
            <ul className="copilot-examples" aria-label="Suggested financial questions">
              {suggestedQuestions.map(({ title, prompt: question, icon }) => {
                const Icon = questionIcons[icon];
                return <li key={question}><button type="button" onClick={() => fillQuestion(question)} disabled={Boolean(busy) || !active}>
                  <span className="copilot-example-icon"><Icon aria-hidden="true" /></span>
                  <span><strong>{title}</strong><span>{question}</span></span>
                  <FiArrowRight className="copilot-example-arrow" aria-hidden="true" />
                </button></li>;
              })}
            </ul>
          </div>}

          {(turns.length > 0 || pending) && <section aria-label="Conversation" className="copilot-conversation">
            {turns.map(({ id, prompt: question, response }, index) => <article key={id} tabIndex={-1}
              ref={(element) => { if (element) turnElements.current.set(index, element); else turnElements.current.delete(index); }}>
              <p className="copilot-question"><span className="copilot-sr-only">You: </span>{question}</p>
              <div className="copilot-assistant">
                <span className="copilot-avatar"><FiZap aria-hidden="true" /></span>
                <div><h3>Copilot</h3><CopilotResponse response={response} /></div>
              </div>
            </article>)}
            {pending && <article>
              <p className="copilot-question"><span className="copilot-sr-only">You: </span>{pending}</p>
              <div className="copilot-generating" role="status">
                <span className="copilot-spinner" aria-hidden="true" /> Calculating from your records…
              </div>
            </article>}
            <div ref={tail} />
          </section>}

          {latest && !pending && active && <div className="copilot-followups">
            <h2>Ask a follow-up</h2>
            <ul>{followUpQuestions(latest).map((question) => <li key={question}>
              <button type="button" onClick={() => fillQuestion(question)} disabled={Boolean(busy)}>
                {question} <FiArrowRight aria-hidden="true" />
              </button>
            </li>)}</ul>
          </div>}

          <p role="status" className="copilot-sr-only">{latest && !pending ? "Copilot response available." : ""}</p>
          {error && <div role="alert" className="copilot-error">
            <p>{error}</p>
            {canSend && <button type="button" className="copilot-text-button" onClick={() => form.current?.requestSubmit()}>Retry question</button>}
          </div>}
          {loading && <p className="copilot-loading" role="status">Refreshing conversation…</p>}
          <form ref={form} onSubmit={ask} className="copilot-composer">
            <label htmlFor="copilot-question">Ask about your finances</label>
            <div className="copilot-entry">
              <textarea ref={input} id="copilot-question" required maxLength={2000} rows={2} value={prompt}
                placeholder="Ask a question about your finances…"
                aria-describedby="copilot-keyboard"
                disabled={!active} readOnly={Boolean(busy)}
                onChange={(event) => setPrompt(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
                  event.preventDefault();
                  if (canSend) form.current?.requestSubmit();
                }} />
              <button className="copilot-send" type="submit" disabled={!canSend}>
                <FiArrowUp aria-hidden="true" /> Send
              </button>
            </div>
            {settings.sharing_enabled
              ? <label className="copilot-consent"><input type="checkbox" checked={consent} disabled={Boolean(busy) || loading}
                onChange={(event) => setConsent(event.target.checked)} /> Allow Gemini to process my questions and recent conversation context in this session</label>
              : <p className="copilot-sharing-off"><FiShield aria-hidden="true" /> AI data sharing is off. You can still view or delete saved history.</p>}
            <p id="copilot-keyboard" className="copilot-keyboard">Enter to send · Shift + Enter for a new line</p>
          </form>
        </section>
      </div>}
    </main>
  );
}
