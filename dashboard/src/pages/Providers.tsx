import { Check, Eye, KeyRound, Pause, Play, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { Gate } from "../components/Gate";
import { ConfirmAction } from "../components/ConfirmAction";
import { PasswordInput } from "../components/PasswordInput";
import { RevealSecret } from "../components/RevealSecret";
import { ErrorBanner, PageHeader, Skeleton, StatusBadge } from "../components/ui";
import { api } from "../lib/api";
import { compact, usd } from "../lib/format";
import { useConnection } from "../lib/store";
import type { AccountProvider } from "../lib/types";
import { useAsync } from "../lib/useAsync";

function ProviderRow({
  provider,
  models,
  onChanged,
}: {
  provider: AccountProvider;
  models: string[];
  onChanged: () => void;
}) {
  const { conn } = useConnection();
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [viewing, setViewing] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  async function save() {
    setBusy(true);
    setMessage(null);
    try {
      const r = await api.putProviderKey(conn, provider.id, key.trim());
      setMessage({
        ok: true,
        text: r.verified ? "Key verified and saved." : "Key saved (provider could not verify it).",
      });
      onChanged();
    } catch (e) {
      setMessage({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setKey(""); // never keep the secret in component state longer than the request
      setBusy(false);
    }
  }

  async function setPaused(paused: boolean) {
    setBusy(true);
    setMessage(null);
    try {
      await api.pauseProviderKey(conn, provider.id, paused);
      // pausing shows its own persistent note on the card, so only resuming needs a message
      if (!paused) setMessage({ ok: true, text: "Resumed. This provider is available for routing again." });
      onChanged();
    } catch (e) {
      setMessage({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <div className="panel-head">
        <div className="form-row" style={{ gap: 12 }}>
          <h2 className="section-title mono">{provider.id}</h2>
          {provider.configured ? (
            provider.paused ? (
              <span className="badge warn">
                <Pause size={12} aria-hidden />
                Paused
              </span>
            ) : provider.auth_failed ? (
              <StatusBadge status="disabled" />
            ) : (
              <StatusBadge status="ready" label="Key saved" detail={`ending ${provider.last4 ?? ""}`} />
            )
          ) : (
            <StatusBadge status="nokey" label="No key yet" />
          )}
        </div>
        {provider.trains_on_data && (
          <span className="badge warn">
            <ShieldAlert size={12} aria-hidden />
            May train on prompts
          </span>
        )}
      </div>
      <div className="panel-body stack">
        {provider.paused && (
          <div className="banner" role="status">
            <Pause size={16} aria-hidden />
            <div className="grow">
              Paused: the key is kept, but LLMFlow will not route requests to {provider.id} until you
              resume it.
            </div>
          </div>
        )}
        <div className="muted">
          Models available once a key is saved: <span className="mono">{models.join(", ") || "none"}</span>
        </div>
        <div className="form-row">
          <div className="field grow">
            <label htmlFor={`key-${provider.id}`}>
              {provider.configured ? "Replace API key" : "API key"}
            </label>
            <PasswordInput
              id={`key-${provider.id}`}
              autoComplete="off"
              placeholder="Paste your provider API key"
              value={key}
              onChange={(e) => setKey(e.target.value)}
            />
          </div>
          <button className="btn primary" disabled={busy || key.trim().length < 8} onClick={() => void save()}>
            <KeyRound size={14} aria-hidden />
            {busy ? "Verifying…" : "Verify and save"}
          </button>
          {provider.configured && (
            <button className="btn" disabled={busy || viewing} onClick={() => setViewing(true)}>
              <Eye size={14} aria-hidden />
              View key
            </button>
          )}
          {provider.configured && (
            <button className="btn" disabled={busy} onClick={() => void setPaused(!provider.paused)}>
              {provider.paused ? <Play size={14} aria-hidden /> : <Pause size={14} aria-hidden />}
              {provider.paused ? "Resume" : "Pause"}
            </button>
          )}
          {provider.configured && (
            <button className="btn" disabled={busy || removing} onClick={() => setRemoving(true)}>
              Remove
            </button>
          )}
        </div>
        {removing && (
          <ConfirmAction
            prompt={`Confirm with your password to remove the ${provider.id} key`}
            confirmLabel="Remove key"
            danger
            onConfirm={async (password, code) => {
              await api.deleteProviderKey(conn, provider.id, password, code);
              setRemoving(false);
              setMessage({ ok: true, text: "Key removed." });
              onChanged();
            }}
            onCancel={() => setRemoving(false)}
          />
        )}
        {viewing && (
          <RevealSecret
            title={`${provider.id} API key`}
            reveal={async (password, code) =>
              (await api.revealProviderKey(conn, provider.id, password, code)).api_key
            }
            onClose={() => setViewing(false)}
          />
        )}
        {message && (
          <span role="status" className={message.ok ? "badge good" : "badge bad"}>
            {message.ok && <Check size={12} aria-hidden />}
            {message.text}
          </span>
        )}
      </div>
    </section>
  );
}

function Body() {
  const { conn, profile } = useConnection();
  const workspace = profile?.workspace.name;
  const { data, error, loading, reload } = useAsync(() => api.account(conn), [conn]);

  return (
    <>
      <PageHeader
        title="Providers"
        description={`Workspace${workspace ? ` “${workspace}”` : ""}: requests are routed only through the provider keys you add here.`}
      />
      {error && <ErrorBanner message={error.message} onRetry={reload} />}
      {!data && loading && (
        <div className="panel panel-body stack">
          <Skeleton height={24} />
          <Skeleton height={120} />
        </div>
      )}
      {data && (
        <>
          <div className="banner" role="note">
            <KeyRound size={16} aria-hidden />
            <div className="grow">
              Keys are verified with the provider and encrypted at rest and in transit. Only the last four characters
              are shown here; use <b>View key</b> to see a saved key after confirming your password. Use a dedicated key with a spend limit, not your main one. Today: {compact(data.usage_today.tokens)} tokens ·{" "}
              {usd(data.usage_today.shadow_cost_usd)} shadow cost.
            </div>
          </div>

          {data.providers.map((p) => (
            <ProviderRow
              key={p.id}
              provider={p}
              models={data.models.filter((m) => m.provider === p.id).map((m) => m.id)}
              onChanged={reload}
            />
          ))}

        </>
      )}
    </>
  );
}

export function Providers() {
  return (
    <div className="page">
      <Gate>
        <Body />
      </Gate>
    </div>
  );
}
