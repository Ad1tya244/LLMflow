import { useState } from "react";
import { Gate } from "../components/Gate";
import { PasswordInput } from "../components/PasswordInput";
import { SecretBlock } from "../components/Secrets";
import { ErrorBanner, PageHeader, PasswordRules, Skeleton } from "../components/ui";
import { passwordAcceptable } from "../lib/passwordRules";
import { api } from "../lib/api";
import { dateTime, deviceLabel } from "../lib/format";
import { useConnection } from "../lib/store";
import { useAsync } from "../lib/useAsync";

const ACTION_LABEL: Record<string, string> = {
  "workspace.created": "Workspace created",
  "login.succeeded": "Signed in",
  "login.failed": "Failed sign-in attempt",
  "password.changed": "Password changed",
  "password.recovered": "Password reset with recovery code",
  "recovery_codes.regenerated": "Recovery codes regenerated",
  "mfa.enabled": "Two-factor authentication turned on",
  "mfa.disabled": "Two-factor authentication turned off",
  "mfa.failed": "Failed second-factor attempt",
  "login.recovery_code_used": "Signed in with a recovery code",
  "api_key.created": "API key created",
  "api_key.revoked": "API key revoked",
  "provider_key.saved": "Provider key saved",
  "provider_key.removed": "Provider key removed",
  "settings.changed": "Workspace settings changed",
  "provider_key.paused": "Provider paused",
  "provider_key.resumed": "Provider resumed",
  "provider_key.revealed": "Provider key viewed",
  "api_key.revealed": "API key viewed",
  "session.revoked": "Session signed out",
};

function SessionsPanel() {
  const { conn } = useConnection();
  const sessions = useAsync(() => api.sessions(conn), [conn]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const rows = sessions.data?.sessions ?? [];
  const others = rows.filter((r) => !r.current).length;

  async function run(action: () => Promise<string>) {
    setBusy(true);
    setMsg(null);
    try {
      setMsg({ ok: true, text: await action() });
      sessions.reload();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <div className="panel-head">
        <div className="card-intro">
          <h2 className="section-title">Active sessions</h2>
          <span className="section-note">Where you are signed in. Sign out any you do not recognise.</span>
        </div>
        <button
          className="btn"
          disabled={busy || others === 0}
          onClick={() =>
            void run(async () => {
              const r = await api.revokeOtherSessions(conn);
              return `Signed out ${r.revoked} other session${r.revoked === 1 ? "" : "s"}.`;
            })
          }
        >
          Sign out other sessions
        </button>
      </div>
      {sessions.error && <ErrorBanner message={sessions.error.message} onRetry={sessions.reload} />}
      {!sessions.data && sessions.loading && (
        <div className="panel-body">
          <Skeleton height={24} />
        </div>
      )}
      {sessions.data && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Device</th>
                <th>IP</th>
                <th>Signed in</th>
                <th>Last active</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>
                    {deviceLabel(r.user_agent)} {r.current && <span className="badge good">This device</span>}
                  </td>
                  <td className="mono muted">{r.ip || "–"}</td>
                  <td className="muted">{dateTime(r.created_at, true)}</td>
                  <td className="muted">{dateTime(r.last_seen_at, true)}</td>
                  <td style={{ textAlign: "right" }}>
                    {!r.current && (
                      <button
                        className="btn ghost"
                        disabled={busy}
                        onClick={() =>
                          void run(async () => {
                            await api.revokeSession(conn, r.id);
                            return "Session signed out.";
                          })
                        }
                      >
                        Sign out
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {msg && (
        <div className="panel-body">
          <span role="status" className={msg.ok ? "badge good" : "badge bad"}>
            {msg.text}
          </span>
        </div>
      )}
    </section>
  );
}

function DangerZone({ workspaceName }: { workspaceName: string }) {
  const { conn, signOut } = useConnection();
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ready = password.length > 0 && name.trim() === workspaceName;

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await api.deleteWorkspace(conn, password, name.trim());
      await signOut();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPassword("");
      setBusy(false);
    }
  }

  return (
    <section className="panel panel-body stack danger-zone">
      <div className="card-intro">
        <h2 className="section-title">Delete workspace</h2>
        <p className="muted">
          Permanently deletes this workspace, its provider keys, API keys, request history and security log. Your
          apps stop working immediately. This cannot be undone.
        </p>
      </div>
      {!open ? (
        <div>
          <button className="btn" onClick={() => setOpen(true)}>
            Delete this workspace…
          </button>
        </div>
      ) : (
        <>
          <div className="form-row">
            <div className="field grow">
              <label htmlFor="del-name">
                Type the workspace name (<b>{workspaceName}</b>) to confirm
              </label>
              <input id="del-name" className="input" autoComplete="off" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="field grow">
              <label htmlFor="del-pw">Your password</label>
              <PasswordInput id="del-pw" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
          </div>
          <div className="form-row">
            <button className="btn danger" disabled={busy || !ready} onClick={() => void remove()}>
              {busy ? "Deleting…" : "Permanently delete workspace"}
            </button>
            <button className="btn ghost" disabled={busy} onClick={() => { setOpen(false); setName(""); setPassword(""); setError(null); }}>
              Cancel
            </button>
            {error && (
              <span role="alert" className="badge bad">
                {error}
              </span>
            )}
          </div>
        </>
      )}
    </section>
  );
}

function Body() {
  const { conn, profile, signOut } = useConnection();
  const account = useAsync(() => api.account(conn), [conn]);
  const audit = useAsync(() => api.audit(conn), [conn]);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [rcPassword, setRcPassword] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [mfaPassword, setMfaPassword] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [mfaSetup, setMfaSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [mfaMsg, setMfaMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function mfa(action: () => Promise<void>) {
    setBusy(true);
    setMfaMsg(null);
    try {
      await action();
      account.reload();
      audit.reload();
    } catch (e) {
      setMfaMsg({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setMfaPassword("");
      setMfaCode("");
      setBusy(false);
    }
  }

  async function changePassword() {
    setMsg(null);
    if (next !== confirm) {
      setMsg({ ok: false, text: "The new passwords do not match." });
      return;
    }
    setBusy(true);
    try {
      await api.changePassword(conn, current, next);
      setMsg({ ok: true, text: "Password changed. Signing you out of all devices…" });
      setTimeout(() => void signOut(), 1200);
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setCurrent("");
      setNext("");
      setConfirm("");
      setBusy(false);
    }
  }

  async function regenerate() {
    setBusy(true);
    setMsg(null);
    try {
      setCodes((await api.regenerateRecoveryCodes(conn, rcPassword)).recovery_codes);
      account.reload();
      audit.reload();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setRcPassword("");
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Account" description="Your sign-in, recovery options and a record of security events." />

      <section className="panel">
        <div className="panel-head">
          <h2 className="section-title">Profile</h2>
        </div>
        <dl className="kv kv-left panel-body">
          <dt>Email</dt>
          <dd>{profile?.user.email}</dd>
          <dt>Workspace</dt>
          <dd>{profile?.workspace.name}</dd>
          <dt>Recovery codes left</dt>
          <dd>{account.data ? account.data.recovery_codes_left : "–"}</dd>
        </dl>
      </section>

      <div className="settings-cols">
        <div className="settings-col">
      <section className="panel panel-body stack">
        <div className="card-intro">
          <h2 className="section-title">Change password</h2>
          <p className="muted">Changing your password signs you out of every device.</p>
        </div>
        <div className="field">
          <label htmlFor="cur">Current password</label>
          <PasswordInput id="cur" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="new">New password</label>
          <PasswordInput id="new" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
          <PasswordRules password={next} email={profile?.user.email} />
        </div>
        <div className="field">
          <label htmlFor="conf">Confirm new password</label>
          <PasswordInput id="conf" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        </div>
        <div className="form-row">
          <button className="btn primary" disabled={busy || !current || !passwordAcceptable(next, profile?.user.email)} onClick={() => void changePassword()}>
            Change password
          </button>
          {msg && <span role="status" className={msg.ok ? "badge good" : "badge bad"}>{msg.text}</span>}
        </div>
      </section>

        </div>
        <div className="settings-col">
      <section className="panel panel-body stack">
        <div className="card-intro">
          <h2 className="section-title">Two-factor authentication</h2>
          <p className="muted">
            {account.data?.user.mfa_enabled
              ? "Enabled. Sign-in needs your password and a code from your authenticator app (or a recovery code)."
              : mfaSetup
                ? "Add this account to an authenticator app (Google Authenticator, 1Password, Authy…): choose “enter a setup key”, paste the key below, then enter the 6-digit code it shows."
                : "Protects your provider keys even if your password leaks. Strongly recommended."}
          </p>
        </div>
        {account.data?.user.mfa_enabled ? (
          <>
            <div className="form-row">
              <div className="field grow">
                <label htmlFor="mfa-pw">Password</label>
                <PasswordInput id="mfa-pw" autoComplete="current-password" value={mfaPassword} onChange={(e) => setMfaPassword(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="mfa-code">Current code</label>
                <input id="mfa-code" className="input" inputMode="numeric" autoComplete="one-time-code" value={mfaCode} onChange={(e) => setMfaCode(e.target.value)} />
              </div>
              <button
                className="btn"
                disabled={busy || !mfaPassword || !mfaCode}
                onClick={() => void mfa(async () => { await api.mfaDisable(conn, mfaPassword, mfaCode); setMfaSetup(null); })}
              >
                Turn off
              </button>
            </div>
          </>
        ) : mfaSetup ? (
          <>
            <SecretBlock title="Setup key" value={mfaSetup.secret} />
            <a className="link" href={mfaSetup.otpauth_uri}>
              Open in authenticator app
            </a>
            <div className="form-row">
              <div className="field">
                <label htmlFor="mfa-confirm">6-digit code</label>
                <input id="mfa-confirm" className="input" inputMode="numeric" autoComplete="one-time-code" value={mfaCode} onChange={(e) => setMfaCode(e.target.value)} />
              </div>
              <button
                className="btn primary"
                disabled={busy || !mfaCode}
                onClick={() => void mfa(async () => { await api.mfaEnable(conn, mfaCode); setMfaSetup(null); })}
              >
                Confirm and turn on
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="form-row">
              <div className="field grow">
                <label htmlFor="mfa-start">Confirm with your password</label>
                <PasswordInput id="mfa-start" autoComplete="current-password" value={mfaPassword} onChange={(e) => setMfaPassword(e.target.value)} />
              </div>
              <button
                className="btn primary"
                disabled={busy || !mfaPassword}
                onClick={() => void mfa(async () => setMfaSetup(await api.mfaSetup(conn, mfaPassword)))}
              >
                Set up
              </button>
            </div>
          </>
        )}
        {mfaMsg && <span role="status" className={mfaMsg.ok ? "badge good" : "badge bad"}>{mfaMsg.text}</span>}
      </section>

      <section className="panel panel-body stack">
        <div className="card-intro">
          <h2 className="section-title">Recovery codes</h2>
          <p className="muted">
            One-time codes that let you reset your password if you forget it. Generating new codes
            invalidates all old ones.
          </p>
        </div>
        <div className="form-row">
          <div className="field grow">
            <label htmlFor="rcp">Confirm with your password</label>
            <PasswordInput id="rcp" autoComplete="current-password" value={rcPassword} onChange={(e) => setRcPassword(e.target.value)} />
          </div>
          <button className="btn" disabled={busy || !rcPassword} onClick={() => void regenerate()}>
            Generate new codes
          </button>
        </div>
        {codes && (
          <div className="banner" role="alert">
            <div className="grow">
              <SecretBlock title="New recovery codes (shown once)" value={codes.join("\n")} filename="llmflow-recovery-codes.txt" />
            </div>
          </div>
        )}
      </section>

        </div>
      </div>

      <SessionsPanel />

      <section className="panel">
        <div className="panel-head">
          <h2 className="section-title">Security activity</h2>
          <span className="section-note">Last 100 events for this workspace</span>
        </div>
        {audit.error && <ErrorBanner message={audit.error.message} onRetry={audit.reload} />}
        {!audit.data && audit.loading && (
          <div className="panel-body">
            <Skeleton height={24} />
          </div>
        )}
        {audit.data && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Event</th>
                  <th>Detail</th>
                  <th>Actor</th>
                  <th>IP</th>
                </tr>
              </thead>
              <tbody>
                {audit.data.events.map((e, i) => (
                  <tr key={`${e.ts}-${i}`}>
                    <td className="muted">{dateTime(e.ts, true)}</td>
                    <td>{ACTION_LABEL[e.action] ?? e.action}</td>
                    <td className="mono">{e.detail || "–"}</td>
                    <td>{e.actor}</td>
                    <td className="mono muted">{e.ip || "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <DangerZone workspaceName={profile?.workspace.name ?? ""} />
    </>
  );
}

export function Settings() {
  return (
    <div className="page">
      <Gate>
        <Body />
      </Gate>
    </div>
  );
}
