import { Eye, EyeOff } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { PasswordInput } from "./PasswordInput";
import { SecretBlock } from "./Secrets";

const VISIBLE_SECONDS = 60;

/** Asks the user to re-enter their password (and authenticator code when needed), then shows a
 *  saved secret with Copy. It hides itself after a minute and keeps nothing once closed. */
export function RevealSecret({
  title,
  reveal,
  onClose,
}: {
  title: string;
  reveal: (password: string, code?: string) => Promise<string>;
  onClose: () => void;
}) {
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [needsCode, setNeedsCode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [secret, setSecret] = useState<string | null>(null);
  const [left, setLeft] = useState(VISIBLE_SECONDS);

  useEffect(() => {
    if (secret === null) return;
    setLeft(VISIBLE_SECONDS);
    const timer = setInterval(() => {
      setLeft((s) => {
        if (s <= 1) {
          clearInterval(timer);
          setSecret(null);
          onClose();
          return 0;
        }
        return s - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [secret]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setSecret(await reveal(password, needsCode ? code.trim() : undefined));
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (/authenticator/i.test(message)) setNeedsCode(true);
      setError(message);
    } finally {
      setPassword("");
      setCode("");
      setBusy(false);
    }
  }

  if (secret !== null) {
    return (
      <div className="reveal stack">
        <div className="form-row" style={{ justifyContent: "space-between" }}>
          <span className="section-note">Hides automatically in {left}s</span>
          <button
            className="btn ghost"
            onClick={() => {
              setSecret(null);
              onClose();
            }}
          >
            <EyeOff size={14} aria-hidden />
            Hide
          </button>
        </div>
        <SecretBlock title={title} value={secret} />
      </div>
    );
  }

  return (
    <form className="reveal stack" onSubmit={(e) => void submit(e)}>
      <div className="form-row">
        <div className="field grow">
          <label htmlFor="reveal-pw">Confirm with your password to view “{title}”</label>
          <PasswordInput
            id="reveal-pw"
            autoFocus
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        {needsCode && (
          <div className="field">
            <label htmlFor="reveal-code">Authenticator code</label>
            <input
              id="reveal-code"
              className="input"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              style={{ width: 140 }}
            />
          </div>
        )}
        <button className="btn primary" type="submit" disabled={busy || !password || (needsCode && !code.trim())}>
          <Eye size={14} aria-hidden />
          {busy ? "Checking…" : "Show key"}
        </button>
        <button className="btn ghost" type="button" disabled={busy} onClick={onClose}>
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
