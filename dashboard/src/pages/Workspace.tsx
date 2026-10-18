import { useEffect, useState } from "react";
import { Gate } from "../components/Gate";
import { ErrorBanner, PageHeader, Segmented, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { compact, usd } from "../lib/format";
import { useConnection } from "../lib/store";
import type { WorkspaceSettings } from "../lib/types";
import { useAsync } from "../lib/useAsync";

type Cache = WorkspaceSettings["cache_mode"];
type Quality = WorkspaceSettings["default_quality"];

const CACHE_OPTIONS: { value: Cache; title: string; body: string }[] = [
  {
    value: "auto",
    title: "Auto (recommended)",
    body: "Cache only requests that are meant to be repeatable (temperature 0). Everything else is answered fresh.",
  },
  {
    value: "always",
    title: "Always",
    body: "Cache every non-streaming request, so identical repeats are free. Replies to the same prompt will be identical.",
  },
  { value: "off", title: "Off", body: "Never cache. Every request calls a model." },
];

function parsePositive(text: string): number | null | "invalid" {
  const t = text.trim();
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) && n > 0 ? n : "invalid";
}

function Form({ initial, reload }: { initial: WorkspaceSettings; reload: () => void }) {
  const { conn } = useConnection();
  const [cache, setCache] = useState<Cache>(initial.cache_mode);
  const [quality, setQuality] = useState<Quality>(initial.default_quality);
  const [usdText, setUsdText] = useState(initial.daily_budget_usd?.toString() ?? "");
  const [tokenText, setTokenText] = useState(initial.daily_token_budget?.toString() ?? "");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    setCache(initial.cache_mode);
    setQuality(initial.default_quality);
    setUsdText(initial.daily_budget_usd?.toString() ?? "");
    setTokenText(initial.daily_token_budget?.toString() ?? "");
  }, [initial]);

  const budget = parsePositive(usdText);
  const tokens = parsePositive(tokenText);
  const invalid = budget === "invalid" || tokens === "invalid" || (typeof tokens === "number" && !Number.isInteger(tokens));
  const dirty =
    cache !== initial.cache_mode ||
    quality !== initial.default_quality ||
    budget !== initial.daily_budget_usd ||
    tokens !== initial.daily_token_budget;

  async function save() {
    if (budget === "invalid" || tokens === "invalid" || invalid) return;
    setBusy(true);
    setMsg(null);
    try {
      await api.saveSettings(conn, {
        cache_mode: cache,
        default_quality: quality,
        daily_budget_usd: budget,
        daily_token_budget: tokens,
      });
      setMsg({ ok: true, text: "Saved. New requests use these settings." });
      reload();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }

  const caps = initial.platform_caps;

  return (
    <>
      <div className="settings-cols">
      <div className="settings-col">
      <section className="panel panel-body stack">
        <div className="card-intro">
          <h2 className="section-title">Response caching</h2>
          <p className="muted">
            Identical requests can be answered from a stored reply at no cost. A request can still override this
            with <code>llmflow.cache</code>.
          </p>
        </div>
        <div className="choice-list" role="radiogroup" aria-label="Response caching">
          {CACHE_OPTIONS.map((o) => (
            <label key={o.value} className={`choice${cache === o.value ? " selected" : ""}`}>
              <input type="radio" name="cache" checked={cache === o.value} onChange={() => setCache(o.value)} />
              <span>
                <b>{o.title}</b>
                <span className="muted">{o.body}</span>
              </span>
            </label>
          ))}
        </div>
      </section>

      </div>
      <div className="settings-col">
      <section className="panel panel-body stack">
        <div className="card-intro">
          <h2 className="section-title">Default quality</h2>
          <p className="muted">
            Used when a request does not set <code>llmflow.quality</code>. Higher quality sends more requests to the
            larger, costlier model.
          </p>
        </div>
        <Segmented
          label="Default quality"
          value={quality}
          onChange={setQuality}
          options={[
            { value: "low", label: "Low" },
            { value: "balanced", label: "Balanced" },
            { value: "high", label: "High" },
          ]}
        />
      </section>

      <section className="panel panel-body stack">
        <div className="card-intro">
          <h2 className="section-title">Daily limits</h2>
          <p className="muted">
            Stop this workspace from spending more than a set amount each day (UTC). Leave a field empty for no
            limit. Requests over the limit are rejected until 00:00 UTC.
            {(caps.daily_budget_usd !== null || caps.daily_token_budget !== null) &&
              ` The gateway also enforces its own caps (${[
                caps.daily_budget_usd !== null ? usd(caps.daily_budget_usd) : null,
                caps.daily_token_budget !== null ? `${compact(caps.daily_token_budget)} tokens` : null,
              ]
                .filter(Boolean)
                .join(", ")}); the stricter limit applies.`}
          </p>
        </div>
        <div className="form-row">
          <div className="field grow">
            <label htmlFor="b-usd">Cost limit per day (USD, shadow cost)</label>
            <input
              id="b-usd"
              className="input"
              inputMode="decimal"
              placeholder="No limit"
              value={usdText}
              onChange={(e) => setUsdText(e.target.value)}
            />
          </div>
          <div className="field grow">
            <label htmlFor="b-tok">Token limit per day</label>
            <input
              id="b-tok"
              className="input"
              inputMode="numeric"
              placeholder="No limit"
              value={tokenText}
              onChange={(e) => setTokenText(e.target.value)}
            />
          </div>
        </div>
        {invalid && <span className="badge bad">Enter a positive number (tokens must be a whole number).</span>}
      </section>

      </div>
      </div>

      <div className="form-row">
        <button className="btn primary" disabled={busy || invalid || !dirty} onClick={() => void save()}>
          {busy ? "Saving…" : "Save changes"}
        </button>
        {msg && (
          <span role="status" className={msg.ok ? "badge good" : "badge bad"}>
            {msg.text}
          </span>
        )}
      </div>
    </>
  );
}

function Body() {
  const { conn } = useConnection();
  const { data, error, loading, reload } = useAsync(() => api.settings(conn), [conn]);
  return (
    <>
      <PageHeader title="Workspace" description="Defaults that apply to every request from this workspace's apps." />
      {error && <ErrorBanner message={error.message} onRetry={reload} />}
      {!data && loading && (
        <div className="panel panel-body stack">
          <Skeleton height={24} />
          <Skeleton height={120} />
        </div>
      )}
      {data && (
        <Form initial={data} reload={reload} />
      )}
    </>
  );
}

export function WorkspacePage() {
  return (
    <div className="page">
      <Gate>
        <Body />
      </Gate>
    </div>
  );
}
