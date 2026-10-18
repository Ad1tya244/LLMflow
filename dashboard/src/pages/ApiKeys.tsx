import { Eye, KeyRound } from "lucide-react";
import { Fragment, useState } from "react";
import { Gate } from "../components/Gate";
import { RevealSecret } from "../components/RevealSecret";
import { SecretBlock } from "../components/Secrets";
import { EmptyState, ErrorBanner, PageHeader, Skeleton, StatusBadge } from "../components/ui";
import { api } from "../lib/api";
import { dateTime } from "../lib/format";
import { useConnection } from "../lib/store";
import { useAsync } from "../lib/useAsync";

function Body() {
  const { conn } = useConnection();
  const { data, error, loading, reload } = useAsync(() => api.apiKeys(conn), [conn]);
  const [name, setName] = useState("");
  const [fresh, setFresh] = useState<{ name: string; api_key: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [viewing, setViewing] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setActionError(null);
    try {
      await fn();
      reload();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="API keys"
        description="Keys your applications send to LLMFlow. Give each app its own key so you can revoke one without breaking the rest."
      />
      {error && <ErrorBanner message={error.message} onRetry={reload} />}
      {actionError && <ErrorBanner message={actionError} />}

      <section className="panel panel-body stack">
        <h2 className="section-title">Create a key</h2>
        <div className="form-row">
          <div className="field grow">
            <label htmlFor="key-name">Name</label>
            <input
              id="key-name"
              className="input"
              value={name}
              maxLength={60}
              placeholder="e.g. production backend"
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <button
            className="btn primary"
            disabled={busy || !name.trim()}
            onClick={() =>
              void run(async () => {
                const k = await api.createApiKey(conn, name.trim());
                setFresh({ name: k.name, api_key: k.api_key });
                setName("");
              })
            }
          >
            <KeyRound size={14} aria-hidden />
            Create key
          </button>
        </div>
        {fresh && (
          <div className="banner" role="alert">
            <div className="grow">
              <SecretBlock
                title={`“${fresh.name}”: copy it now, it will not be shown again`}
                value={fresh.api_key}
                filename="llmflow-api-key.txt"
              />
            </div>
          </div>
        )}
      </section>

      {!data && loading && (
        <div className="panel panel-body stack">
          <Skeleton height={24} />
          <Skeleton height={24} />
        </div>
      )}
      {data && (
        <section className="panel">
          {data.keys.length === 0 ? (
            <EmptyState title="No keys yet">Create one above to start sending requests.</EmptyState>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Key</th>
                    <th>Status</th>
                    <th>Created</th>
                    <th>Last used</th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {data.keys.map((k) => (
                    <Fragment key={k.id}>
                    <tr>
                      <td>{k.name}</td>
                      <td className="mono">llmf_…{k.last4}</td>
                      <td>
                        {k.revoked_at ? (
                          <StatusBadge status="error" label="Revoked" />
                        ) : (
                          <StatusBadge status="ok" label="Active" />
                        )}
                      </td>
                      <td className="muted">{dateTime(k.created_at)}</td>
                      <td className="muted">{k.last_used_at ? dateTime(k.last_used_at) : "Never"}</td>
                      <td>
                        <div className="row-actions">
                        {!k.revoked_at && (
                          <button
                            className="btn"
                            disabled={!k.revealable || viewing === k.id}
                            title={
                              k.revealable
                                ? "Show the full key"
                                : "Created before key viewing existed. Create a new key to be able to view it later."
                            }
                            onClick={() => setViewing(k.id)}
                          >
                            <Eye size={14} aria-hidden />
                            View
                          </button>
                        )}
                        {!k.revoked_at && (
                          <button
                            className="btn"
                            disabled={busy}
                            onClick={() => {
                              if (window.confirm(`Revoke “${k.name}”? Apps using it will stop working immediately.`)) {
                                void run(() => api.revokeApiKey(conn, k.id).then(() => undefined));
                              }
                            }}
                          >
                            Revoke
                          </button>
                        )}
                        </div>
                      </td>
                    </tr>
                    {viewing === k.id && (
                      <tr className="reveal-row">
                        <td colSpan={6}>
                          <RevealSecret
                            title={`${k.name} (llmf_…${k.last4})`}
                            reveal={async (password, code) =>
                              (await api.revealApiKey(conn, k.id, password, code)).api_key
                            }
                            onClose={() => setViewing(null)}
                          />
                        </td>
                      </tr>
                    )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </>
  );
}

export function ApiKeys() {
  return (
    <div className="page">
      <Gate>
        <Body />
      </Gate>
    </div>
  );
}
