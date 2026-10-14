import { passwordRules } from "../lib/passwordRules";
import { AlertTriangle, Check, CircleAlert, Clock, KeyRound, Minus } from "lucide-react";
import type { ReactNode } from "react";
import type { Tier } from "../lib/types";

export function PageHeader({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children?: ReactNode;
}) {
  return (
    <header className="page-head">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {children}
    </header>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export interface Stat {
  label: string;
  value: string;
  sub?: string;
}

export function StatStrip({ stats, busy }: { stats: Stat[]; busy?: boolean }) {
  return (
    <div className={`panel stat-strip ${busy ? "refetching" : ""}`}>
      {stats.map((s) => (
        <div className="stat" key={s.label}>
          <span className="label">{s.label}</span>
          <span className="value">{s.value}</span>
          {s.sub && <span className="sub">{s.sub}</span>}
        </div>
      ))}
    </div>
  );
}

const TIER_VAR: Record<Tier, string> = {
  small: "var(--tier-small)",
  medium: "var(--tier-medium)",
  large: "var(--tier-large)",
};

export function TierBadge({ tier }: { tier: Tier | null }) {
  if (!tier) return <span className="muted">–</span>;
  return (
    <span className="badge">
      <span className="swatch" style={{ background: TIER_VAR[tier] }} />
      {tier}
    </span>
  );
}

export type Status = "ok" | "error" | "ready" | "cooling" | "disabled" | "nokey" | "off";

const STATUS: Record<Status, { label: string; cls: string; icon: ReactNode }> = {
  ok: { label: "OK", cls: "good", icon: <Check size={12} aria-hidden /> },
  ready: { label: "Ready", cls: "good", icon: <Check size={12} aria-hidden /> },
  error: { label: "Error", cls: "bad", icon: <CircleAlert size={12} aria-hidden /> },
  cooling: { label: "Cooling down", cls: "warn", icon: <Clock size={12} aria-hidden /> },
  disabled: { label: "Auth failed", cls: "bad", icon: <KeyRound size={12} aria-hidden /> },
  nokey: { label: "No API key", cls: "", icon: <Minus size={12} aria-hidden /> },
  off: { label: "Disabled in catalog", cls: "", icon: <Minus size={12} aria-hidden /> },
};

export function StatusBadge({
  status,
  detail,
  label,
}: {
  status: Status;
  detail?: string;
  label?: string;
}) {
  const s = STATUS[status];
  return (
    <span className={`badge ${s.cls}`}>
      {s.icon}
      {label ?? s.label}
      {detail ? ` ${detail}` : ""}
    </span>
  );
}

export function Meter({
  used,
  limit,
  label,
  format = (n: number) => n.toLocaleString(),
}: {
  used: number;
  limit: number | null;
  label: string;
  format?: (n: number) => string;
}) {
  if (limit === null) return <span className="muted">no local limit</span>;
  const frac = limit > 0 ? Math.min(1, used / limit) : 0;
  const cls = frac >= 0.9 ? "bad" : frac >= 0.7 ? "warn" : "";
  return (
    <div className="meter">
      <div
        className="meter-track"
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={limit}
        aria-valuenow={used}
      >
        <div className={`meter-fill ${cls}`} style={{ width: `${frac * 100}%` }} />
      </div>
      <span className="meter-label">
        {format(used)} / {format(limit)}
      </span>
    </div>
  );
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="banner bad" role="alert">
      <AlertTriangle size={16} aria-hidden />
      <div className="grow">{message}</div>
      {onRetry && (
        <button className="btn" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Skeleton({ height = 16, width = "100%" }: { height?: number; width?: number | string }) {
  return <div className="skeleton" style={{ height, width }} aria-hidden />;
}

export function PasswordRules({ password, email }: { password: string; email?: string }) {
  return (
    <ul className="pw-rules" aria-label="Password requirements">
      {passwordRules(password, email).map((r) => (
        <li key={r.label} className={r.ok ? "ok" : undefined}>
          {r.label}
          <span className="sr-only">{r.ok ? " (met)" : " (not met)"}</span>
        </li>
      ))}
    </ul>
  );
}
