import { useState, type FormEvent } from "react";
import { PasswordInput } from "./PasswordInput";

/** Asks the user to re-enter their password (and authenticator code when needed) before a
 *  destructive action runs. Nothing happens until the server accepts the credentials. */
export function ConfirmAction({
  prompt,
  confirmLabel,
  danger = false,
  onConfirm,
  onCancel,
}: {
  prompt: string;
  confirmLabel: string;
  danger?: boolean;
  onConfirm: (password: string, code?: string) => Promise<void>;
  onCancel: () => void;
}) {
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [needsCode, setNeedsCode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onConfirm(password, needsCode ? code.trim() : undefined);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (/authenticator/i.test(message)) setNeedsCode(true);
      setError(message);
      setBusy(false);
    } finally {
      setPassword("");
      setCode("");
    }
  }

  return (
    <form className="reveal stack" onSubmit={(e) => void submit(e)}>
      <div className="form-row">
        <div className="field grow">
          <label htmlFor="confirm-pw">{prompt}</label>
          <PasswordInput
            id="confirm-pw"
            autoFocus
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        {needsCode && (
          <div className="field">
            <label htmlFor="confirm-code">Authenticator code</label>
            <input
              id="confirm-code"
              className="input"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              style={{ width: 140 }}
            />
          </div>
        )}
        <button
          className={`btn ${danger ? "danger" : "primary"}`}
          type="submit"
          disabled={busy || !password || (needsCode && !code.trim())}
        >
          {busy ? "Checking…" : confirmLabel}
        </button>
        <button className="btn ghost" type="button" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
      </div>
      {error && (
        <span role="alert" className="badge bad">
          {error}
        </span>
      )}
    </form>
  );
}
