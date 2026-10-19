import { ArrowUp, Check, Copy, Plus } from "lucide-react";
import { Suspense, lazy, useEffect, useRef, useState } from "react";
import { Gate } from "../components/Gate";
import { EmptyState, ErrorBanner, PageHeader, Segmented } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { sendChat, trimHistory, type ChatMessage, type RouteInfo } from "../lib/chat";
import { useConnection } from "../lib/store";
import { useAsync } from "../lib/useAsync";

// Markdown (with tables and math) is only needed here, so it loads on demand.
const Markdown = lazy(() => import("../components/Markdown").then((m) => ({ default: m.Markdown })));

interface Turn extends ChatMessage {
  model?: string;
}

function Body() {
  const { conn } = useConnection();
  const models = useAsync(async () => ({ models: (await api.account(conn)).models }), [conn]);
  const [model, setModel] = useState("auto");
  const [prompt, setPrompt] = useState("");
  const [quality, setQuality] = useState<"low" | "balanced" | "high">("balanced");
  const [strict, setStrict] = useState(false);
  const [stream, setStream] = useState(true);
  const [useCache, setUseCache] = useState(false);
  // One chat = one list of turns. Every send carries this chat's messages (trimmed to a cap),
  // so replies stay in context; "New chat" empties the list and nothing carries over.
  const [turns, setTurns] = useState<Turn[]>([]);
  const [dropped, setDropped] = useState(0);
  const [info, setInfo] = useState<RouteInfo | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [copiedAt, setCopiedAt] = useState<number | null>(null);
  const abort = useRef<AbortController | null>(null);
  const thread = useRef<HTMLDivElement | null>(null);
  const box = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (thread.current) thread.current.scrollTop = thread.current.scrollHeight;
  }, [turns]);

  // The message box grows with what is typed (up to the CSS max-height), then scrolls.
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [prompt]);

  function newChat() {
    abort.current?.abort();
    abort.current = null;
    setTurns([]);
    setDropped(0);
    setInfo(null);
    setError(null);
    setBusy(false);
  }

  async function copyReply(index: number, text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedAt(index);
      setTimeout(() => setCopiedAt((c) => (c === index ? null : c)), 1500);
    } catch {
      /* clipboard unavailable */
    }
  }

  async function run() {
    const content = prompt.trim();
    if (!content || busy) return;
    const ctl = new AbortController();
    abort.current = ctl;
    const history: ChatMessage[] = [
      ...turns.map(({ role, content: c }) => ({ role, content: c })),
      { role: "user", content },
    ];
    const sent = trimHistory(history);
    setDropped(sent.dropped);
    setTurns((t) => [...t, { role: "user", content }, { role: "assistant", content: "" }]);
    setPrompt("");
    setBusy(true);
    setError(null);
    try {
      const result = await sendChat(
        conn,
        { model, messages: sent.messages, quality, privacy: strict ? "strict" : "standard", stream, cache: useCache },
        (text) => setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, content: text } : x))),
        ctl.signal,
      );
      setInfo(result);
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, model: result.model } : x)));
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      // Leave no half-finished exchange in the history: put the message back to retry.
      setTurns((t) => t.slice(0, -2));
      setPrompt(content);
      setError(e instanceof ApiError ? e : new ApiError(String(e), 0, "unknown"));
    } finally {
      if (abort.current === ctl) setBusy(false);
    }
  }

  const enabled = models.data?.models.filter((m) => m.enabled) ?? [];

  return (
    <>
      <PageHeader
        title="Playground"
        description="Chat through the gateway and see how each reply was routed. Messages in the same chat share context."
      />
      <div className="play-grid">
          <section className="panel p-chat">
            <div className="chat-inner">
            <div className="panel-head">
              <h2 className="section-title">Conversation</h2>
              <div className="form-row">
                <button className="btn ghost" onClick={newChat} disabled={turns.length === 0 && !busy}>
                  <Plus size={14} aria-hidden />
                  New chat
                </button>
              </div>
            </div>
            <div className="panel-body chat-scroll" aria-live="polite" ref={thread}>
              {error && <ErrorBanner message={error.message} />}
              {turns.length === 0 && !error && (
                <EmptyState title="Start a conversation">
                  Replies stay in context within this chat. A new chat starts fresh.
                </EmptyState>
              )}
              {turns.length > 0 && (
                <div className="thread">
                  {turns.map((t, i) => (
                    <div key={i} className={`turn turn-${t.role}`}>
                      {t.role === "user" ? (
                        <div className="turn-user-text">{t.content}</div>
                      ) : t.content ? (
                        <div className="response">
                          <Suspense fallback={<div className="response-plain">{t.content}</div>}>
                            <Markdown source={t.content} />
                          </Suspense>
                          {!(busy && i === turns.length - 1) && (
                            <div className="turn-actions">
                              <button
                                className="icon-btn"
                                onClick={() => void copyReply(i, t.content)}
                                aria-label="Copy reply"
                                title={copiedAt === i ? "Copied" : "Copy reply"}
                              >
                                {copiedAt === i ? <Check size={14} aria-hidden /> : <Copy size={14} aria-hidden />}
                              </button>
                              {t.model && <span className="turn-meta">{t.model}</span>}
                            </div>
                          )}
                        </div>
                      ) : (
                        <span className="muted">Waiting for the model…</span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="chat-composer">
              <label htmlFor="prompt" className="sr-only">
                Message
              </label>
              <div className="composer-box">
                <textarea
                  id="prompt"
                  ref={box}
                  rows={1}
                  className="textarea"
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  placeholder={turns.length ? "Reply…" : "Ask something…"}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                      e.preventDefault();
                      void run();
                    }
                  }}
                />
                <button
                  className="send-btn"
                  disabled={!prompt.trim() || busy}
                  onClick={() => void run()}
                  aria-label={busy ? "Sending…" : "Send"}
                  title="Send"
                >
                  <ArrowUp size={16} aria-hidden />
                </button>
              </div>
              <span className="hint">
                {dropped > 0
                  ? "Long chat: the oldest messages are no longer sent. Start a new chat to reset."
                  : "Enter to send, Shift + Enter for a new line"}
              </span>
            </div>
            </div>
          </section>

          <div className="play-side">
          <section className="panel panel-body stack p-options">
            <div className="field">
              <label htmlFor="model">Model</label>
              <select id="model" className="select" value={model} onChange={(e) => setModel(e.target.value)}>
                <option value="auto">auto (router decides)</option>
                {enabled.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.id}
                  </option>
                ))}
              </select>
              {models.data && enabled.length === 0 && (
                <span className="hint">No provider keys configured on the gateway yet.</span>
              )}
            </div>
            <div className="field">
              <label>Quality</label>
              <Segmented
                label="Quality"
                value={quality}
                onChange={setQuality}
                options={[
                  { value: "low", label: "Low" },
                  { value: "balanced", label: "Balanced" },
                  { value: "high", label: "High" },
                ]}
              />
              <span className="hint">Higher quality raises the model bar and the cost.</span>
            </div>
            <label className="check">
              <input type="checkbox" checked={strict} onChange={(e) => setStrict(e.target.checked)} />
              Strict privacy (exclude providers that train on prompts)
            </label>
            <label className="check">
              <input type="checkbox" checked={stream && !useCache} disabled={useCache} onChange={(e) => setStream(e.target.checked)} />
              Stream response
            </label>
            <label className="check">
              <input type="checkbox" checked={useCache} onChange={(e) => setUseCache(e.target.checked)} />
              Use response cache (sends the reply in one piece; repeats are free)
            </label>
          </section>

          <section className="panel p-routing">
            <div className="panel-head">
              <h2 className="section-title">Routing</h2>
            </div>
            <div className="panel-body">
              {info ? (
                <dl className="kv">
                  <dt>Model</dt>
                  <dd>{info.model}</dd>
                  <dt>Provider</dt>
                  <dd>{info.provider}</dd>
                  <dt>Attempts</dt>
                  <dd>{info.attempts}</dd>
                  {info.cache && (
                    <>
                      <dt>Cache</dt>
                      <dd>{info.cache === "hit" ? "Hit (no model call)" : info.cache === "miss" ? "Miss (stored)" : info.cache}</dd>
                    </>
                  )}
                  {info.cost && (
                    <>
                      <dt>Shadow cost</dt>
                      <dd>${info.cost}</dd>
                    </>
                  )}
                  <dt>Reason</dt>
                  <dd className="kv-reason">{info.reason}</dd>
                </dl>
              ) : (
                <span className="muted">Send a request to see the routing decision.</span>
              )}
            </div>
          </section>
          </div>
      </div>
    </>
  );
}

export function Playground() {
  return (
    <div className="page">
      <Gate>
        <Body />
      </Gate>
    </div>
  );
}
