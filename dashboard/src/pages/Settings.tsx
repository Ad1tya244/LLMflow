import { useState } from "react";
import { Gate } from "../components/Gate";
import { SecretBlock } from "../components/Secrets";
import { ErrorBanner, PageHeader, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { dateTime } from "../lib/format";
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
};

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
        <dl className="kv panel-body">
          <dt>Email</dt>
          <dd>{profile?.user.email}</dd>
          <dt>Workspace</dt>
          <dd>{profile?.workspace.name}</dd>
          <dt>Recovery codes left</dt>
          <dd>{account.data ? account.data.recovery_codes_left : "–"}</dd>
        </dl>
      </section>

      <section className="panel panel-body stack" style={{ maxWidth: 560 }}>
        <h2 className="section-title">Change password</h2>
        <p className="muted">Changing your password signs you out of every device.</p>
        <div className="field">
          <label htmlFor="cur">Current password</label>
          <input id="cur" className="input" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="new">New password</label>
          <input id="new" className="input" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
          <span className="hint">At least 12 characters.</span>
        </div>
        <div className="field">
          <label htmlFor="conf">Confirm new password</label>
          <input id="conf" className="input" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        </div>
        <div className="form-row">
          <button className="btn primary" disabled={busy || !current || !next} onClick={() => void changePassword()}>
            Change password
          </button>
          {msg && <span role="status" className={msg.ok ? "badge good" : "badge bad"}>{msg.text}</span>}
        </div>
      </section>

      <section className="panel panel-body stack" style={{ maxWidth: 560 }}>
        <h2 className="section-title">Two-factor authentication</h2>
        {account.data?.user.mfa_enabled ? (
          <>
            <p className="muted">
              Enabled. Sign-in needs your password and a code from your authenticator app (or a recovery code).
            </p>
            <div className="form-row">
              <div className="field grow">
                <label htmlFor="mfa-pw">Password</label>
                <input id="mfa-pw" className="input" type="password" autoComplete="current-password" value={mfaPassword} onChange={(e) => setMfaPassword(e.target.value)} />
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
            <p className="muted">
              Add this account to an authenticator app (Google Authenticator, 1Password, Authy…): choose
              &quot;enter a setup key&quot; and paste the key below, then enter the 6-digit code it shows.
            </p>
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
            <p className="muted">
              Protects your provider keys even if your password leaks. Strongly recommended.
            </p>
            <div className="form-row">
              <div className="field grow">
                <label htmlFor="mfa-start">Confirm with your password</label>
                <input id="mfa-start" className="input" type="password" autoComplete="current-password" value={mfaPassword} onChange={(e) => setMfaPassword(e.target.value)} />
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

      <section className="panel panel-body stack" style={{ maxWidth: 560 }}>
        <h2 className="section-title">Recovery codes</h2>
        <p className="muted">
          One-time codes that let you reset your password if you forget it. Generating new codes
          invalidates all old ones.
        </p>
        <div className="form-row">
          <div className="field grow">
            <label htmlFor="rcp">Confirm with your password</label>
            <input id="rcp" className="input" type="password" autoComplete="current-password" value={rcPassword} onChange={(e) => setRcPassword(e.target.value)} />
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
                    <td className="muted">{dateTime(e.ts)}</td>
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
