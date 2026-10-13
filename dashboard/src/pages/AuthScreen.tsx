import { useState } from "react";
import { SecretBlock } from "../components/Secrets";
import { ErrorBanner } from "../components/ui";
import { api, type SignupResult } from "../lib/api";
import { GATEWAY_URL, useConnection } from "../lib/store";
import type { PublicInfo } from "../lib/types";
import { useAsync } from "../lib/useAsync";

type Mode = "signin" | "signup" | "recover";

function Mark() {
  return (
    <svg width="28" height="28" viewBox="0 0 20 20" aria-hidden>
      <rect width="20" height="20" rx="5" fill="var(--ink)" />
      <path
        d="M3 10h5M8 10l4-4h5M8 10h9M8 10l4 4h5"
        stroke="var(--on-ink)"
        strokeWidth="1.6"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function Field({
  id,
  label,
  type = "text",
  value,
  onChange,
  autoComplete,
  hint,
}: {
  id: string;
  label: string;
  type?: string;
  value: string;
  onChange: (v: string) => void;
  autoComplete?: string;
  hint?: string;
}) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        className="input"
        type={type}
        value={value}
        autoComplete={autoComplete}
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
      />
      {hint && <span className="hint">{hint}</span>}
    </div>
  );
}

/** One-time hand-off of the first API key and the recovery codes after sign-up. */
function SaveSecrets({ result, onDone }: { result: SignupResult; onDone: () => void }) {
  const [confirmed, setConfirmed] = useState(false);
  const codes = result.recovery_codes.join("\n");
  return (
    <div className="auth-card stack">
      <div>
        <h1>Save these now</h1>
        <p className="muted">
          Workspace <b>{result.workspace.name}</b> is ready. These secrets are shown only once and we only
          store hashes, so we cannot show them again.
        </p>
      </div>
      <SecretBlock title="Your first API key" value={result.api_key} filename="llmflow-api-key.txt" />
      <SecretBlock
        title="Recovery codes (each works once to reset your password)"
        value={codes}
        filename="llmflow-recovery-codes.txt"
      />
      <label className="check">
        <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
        I have saved my API key and recovery codes somewhere safe
      </label>
      <button className="btn primary" disabled={!confirmed} onClick={onDone}>
        Continue to dashboard
      </button>
    </div>
  );
}

export function AuthScreen() {
  const { signIn, signInMfa, adopt } = useConnection();
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [mfaCode, setMfaCode] = useState("");
  const info = useAsync<PublicInfo | null>(() => api.publicInfo(GATEWAY_URL), []);
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [invite, setInvite] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [created, setCreated] = useState<SignupResult | null>(null);

  const signupOpen = info.data?.signup_enabled ?? false;

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPassword(""); // secrets never outlive the request in component state
      setBusy(false);
    }
  }

  if (created) {
    return (
      <div className="auth-wrap">
        <SaveSecrets
          result={created}
          onDone={() => adopt({ csrf: created.csrf, workspace: created.workspace, user: created.user })}
        />
      </div>
    );
  }

  if (mfaToken) {
    return (
      <div className="auth-wrap">
        <form
          className="auth-card stack"
          onSubmit={(e) => {
            e.preventDefault();
            void run(async () => {
              try {
                await signInMfa(mfaToken, mfaCode);
              } finally {
                setMfaCode("");
              }
            });
          }}
        >
          <div className="auth-brand">
            <Mark />
            <span>LLMFlow</span>
          </div>
          <div>
            <h1>Two-factor authentication</h1>
            <p className="muted">
              Enter the 6-digit code from your authenticator app, or one of your recovery codes.
            </p>
          </div>
          {error && <ErrorBanner message={error} />}
          <Field id="mfa" label="Code" value={mfaCode} onChange={setMfaCode} autoComplete="one-time-code" />
          <button className="btn primary" type="submit" disabled={busy || !mfaCode.trim()}>
            {busy ? "Please wait…" : "Verify"}
          </button>
          <div className="auth-links">
            <button type="button" className="link" onClick={() => { setMfaToken(null); setError(null); }}>
              Back to sign in
            </button>
          </div>
        </form>
      </div>
    );
  }

  const title = { signin: "Sign in", signup: "Create your workspace", recover: "Reset your password" }[mode];

  return (
    <div className="auth-wrap">
      <form
        className="auth-card stack"
        onSubmit={(e) => {
          e.preventDefault();
          if (mode === "signin")
            void run(async () => {
              const r = await signIn(email.trim(), password);
              if (r) setMfaToken(r.mfaToken);
            });
          else if (mode === "signup")
            void run(async () => {
              const r = await api.signup(GATEWAY_URL, email.trim(), password, workspace.trim(), invite);
              setInvite("");
              setCreated(r);
            });
          else
            void run(async () => {
              await api.recover(GATEWAY_URL, email.trim(), code.trim(), password);
              setCode("");
              setMode("signin");
              setNotice("Password updated. Sign in with your new password.");
            });
        }}
      >
        <div className="auth-brand">
          <Mark />
          <span>LLMFlow</span>
        </div>
        <div>
          <h1>{title}</h1>
          <p className="muted">
            {mode === "signin" && "Use your workspace account to manage keys and see usage."}
            {mode === "signup" && "Bring your own provider keys; we route each request to the right model."}
            {mode === "recover" && "Enter one of the recovery codes you saved when you signed up."}
          </p>
        </div>

        {error && <ErrorBanner message={error} />}
        {notice && (
          <div className="banner" role="status">
            <div className="grow">{notice}</div>
          </div>
        )}
        {info.data === null && !info.loading && (
          <ErrorBanner message="Cannot reach the gateway. If it was idle it may take a minute to wake up." onRetry={info.reload} />
        )}

        {mode === "signup" && (
          <Field id="ws" label="Workspace name" value={workspace} onChange={setWorkspace} autoComplete="organization" />
        )}
        <Field id="email" label="Email" type="email" value={email} onChange={setEmail} autoComplete="username" />
        {mode === "recover" && (
          <Field id="code" label="Recovery code" value={code} onChange={setCode} hint="Format: XXXX-XXXX-XXXX" />
        )}
        <Field
          id="password"
          label={mode === "recover" ? "New password" : "Password"}
          type="password"
          value={password}
          onChange={setPassword}
          autoComplete={mode === "signin" ? "current-password" : "new-password"}
          hint={mode !== "signin" ? "At least 12 characters." : undefined}
        />
        {mode === "signup" && info.data?.invite_code_required && (
          <Field id="invite" label="Invite code" type="password" value={invite} onChange={setInvite} />
        )}

        <button className="btn primary" type="submit" disabled={busy}>
          {busy ? "Please wait…" : title}
        </button>

        <div className="auth-links">
          {mode !== "signin" && (
            <button type="button" className="link" onClick={() => setMode("signin")}>
              Back to sign in
            </button>
          )}
          {mode === "signin" && signupOpen && (
            <button type="button" className="link" onClick={() => setMode("signup")}>
              Create a workspace
            </button>
          )}
          {mode === "signin" && (
            <button type="button" className="link" onClick={() => setMode("recover")}>
              Forgot password?
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
