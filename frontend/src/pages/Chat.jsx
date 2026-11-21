import { useEffect, useState } from "react";
import api from "../api";
import "../styles/pages/Chat.css";

const chat = "/api/chat/";
const examples = [
  "How much did I spend on groceries last month?",
  "Compare my spending in September and October.",
  "Which budget categories are close to their limits?",
];

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

  useEffect(() => {
    const controller = new AbortController();
    const options = { signal: controller.signal };
    Promise.all([api.get(`${chat}settings/`, options), api.get(`${chat}history/`, options)])
      .then(([preferences, history]) => {
        setSettings(preferences.data);
        setTurns(history.data.turns);
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
    setBusy("settings");
    setError("");
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
    try {
      await api.delete(`${chat}history/`);
      setToken(null);
      setTurns([]);
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
    setBusy("answer");
    setError("");
    try {
      const { data } = await api.post(chat, {
        prompt: question,
        consent,
        ...(token ? { context_token: token } : {}),
      });
      const { context_token: nextToken, ...response } = data;
      setToken(nextToken);
      setTurns((previous) => [...previous, { prompt: question, response }].slice(-24));
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
      setBusy("");
    }
  }

  return (
    <main className="copilot-page">
      <h1>Financial Copilot</h1>
      {loading && <p role="status">Loading Copilot…</p>}
      {error && <p role="alert" className="copilot-error">{error}</p>}
      {!settings && !loading && <button type="button" onClick={() => {
        setError("");
        setLoading(true);
        setRevision((value) => value + 1);
      }}>Try again</button>}
      {settings && <>
        <fieldset className="copilot-settings" disabled={Boolean(busy) || loading}>
          <legend>Privacy settings</legend>
          <label><input type="checkbox" checked={settings.sharing_enabled}
            onChange={(event) => updateSetting("sharing_enabled", event.target.checked)} /> Allow sharing with Gemini</label>
          <label><input type="checkbox" checked={settings.history_enabled}
            onChange={(event) => updateSetting("history_enabled", event.target.checked)} /> Save conversation history</label>
          <p>{settings.history_enabled ? "Turning history off deletes the saved conversation." : "Conversation history is kept in this tab while you chat."}</p>
          <button type="button" onClick={clearConversation} disabled={!turns.length && !settings.history_enabled}>
            {settings.history_enabled ? "Delete saved history" : "Clear conversation"}
          </button>
        </fieldset>
        {turns.length === 0 && <ul className="copilot-examples" aria-label="Example questions">
          {examples.map((question) => <li key={question}>
            <button type="button" onClick={() => setPrompt(question)} disabled={Boolean(busy) || !settings.sharing_enabled}>{question}</button>
          </li>)}
        </ul>}
        <section aria-label="Conversation" aria-live="polite" className="copilot-conversation">
          {turns.map(({ prompt: question, response }, index) => <article key={index}>
            <p className="copilot-question"><strong>You</strong> {question}</p>
            <strong>Copilot</strong>
            <p className="copilot-answer">{response.answer}</p>
          </article>)}
          {busy === "answer" && <p role="status">Calculating from your records…</p>}
        </section>
        <form onSubmit={ask} className="copilot-composer">
          <label htmlFor="copilot-question">Ask about your finances</label>
          <textarea id="copilot-question" required maxLength={2000} rows={3} value={prompt}
            disabled={Boolean(busy) || !settings.sharing_enabled}
            onChange={(event) => setPrompt(event.target.value)} />
          {settings.sharing_enabled
            ? <label><input type="checkbox" checked={consent} disabled={Boolean(busy)}
              onChange={(event) => setConsent(event.target.checked)} /> Allow Gemini to process my questions and recent conversation context in this session</label>
            : <p>AI data sharing is off. You can still view or delete saved history.</p>}
          <button type="submit" disabled={Boolean(busy) || loading || !consent || !settings.sharing_enabled || !prompt.trim()}>Send</button>
        </form>
      </>}
    </main>
  );
}
