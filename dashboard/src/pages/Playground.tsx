import { Check, Copy, Send } from "lucide-react";
import { Markdown } from "../components/Markdown";
import { useRef, useState } from "react";
import { Gate } from "../components/Gate";
import { EmptyState, ErrorBanner, PageHeader, Segmented } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { sendChat, type RouteInfo } from "../lib/chat";
import { useConnection } from "../lib/store";
import { useAsync } from "../lib/useAsync";

function Body() {
  const { conn } = useConnection();
  const models = useAsync(async () => ({ models: (await api.account(conn)).models }), [conn]);
  const [model, setModel] = useState("auto");
  const [prompt, setPrompt] = useState("");
  const [quality, setQuality] = useState<"low" | "balanced" | "high">("balanced");
  const [strict, setStrict] = useState(false);
  const [stream, setStream] = useState(true);
  const [useCache, setUseCache] = useState(false);
  const [text, setText] = useState("");
  const [info, setInfo] = useState<RouteInfo | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const abort = useRef<AbortController | null>(null);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  }

  async function run() {
    abort.current?.abort();
    const ctl = new AbortController();
    abort.current = ctl;
    setBusy(true);
    setError(null);
    setText("");
    setInfo(null);
    try {
      const result = await sendChat(
        conn,
        { model, prompt, quality, privacy: strict ? "strict" : "standard", stream, cache: useCache },
        setText,
        ctl.signal,
      );
      setInfo(result);
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
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
        description="Send a request through the gateway and see how it was routed."
      />
      <div className="split">
        <section className="panel">
          <div className="panel-body stack">
            <div className="field">
              <label htmlFor="prompt">Prompt</label>
              <textarea
                id="prompt"
                className="textarea"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="Ask something…"
                onKeyDown={(e) => {
                  if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && prompt.trim() && !busy) void run();
                }}
              />
              <span className="hint">Cmd/Ctrl + Enter to send</span>
            </div>
            <div>
              <button className="btn primary" disabled={!prompt.trim() || busy} onClick={() => void run()}>
                <Send size={14} aria-hidden />
                {busy ? "Sending…" : "Send"}
              </button>
            </div>
          </div>
          <div className="panel-head" style={{ borderTop: "1px solid var(--border)" }}>
            <h2 className="section-title">Response</h2>
            {text && !busy && (
              <button className="btn ghost" onClick={() => void copy()} aria-label="Copy response">
                {copied ? <Check size={14} aria-hidden /> : <Copy size={14} aria-hidden />}
                {copied ? "Copied" : "Copy"}
              </button>
            )}
          </div>
          <div className="panel-body" aria-live="polite">
            {error && <ErrorBanner message={error.message} />}
            {!error && !text && !busy && (
              <EmptyState title="No response yet">The reply and routing details will appear here.</EmptyState>
            )}
            {text && (
              <div className="response">
                {busy ? <div className="response-plain">{text}</div> : <Markdown source={text} />}
              </div>
            )}
          </div>
        </section>

        <aside className="stack">
          <section className="panel panel-body stack">
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

          <section className="panel">
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
        </aside>
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
