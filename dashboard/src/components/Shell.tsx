import {
  Activity,
  KeyRound,
  LogOut,
  MessageSquareText,
  Moon,
  Plug,
  ScrollText,
  Server,
  Settings,
  Sun,
  type LucideIcon,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import type { RouteId } from "../lib/route";
import { GATEWAY_URL, useConnection } from "../lib/store";
import { currentTheme, setTheme } from "../lib/theme";
import { useGatewayHealth } from "../lib/useGatewayHealth";

interface NavItem {
  id: RouteId;
  label: string;
  icon: LucideIcon;
}

const SECTIONS: { label: string; items: NavItem[] }[] = [
  {
    label: "Workspace",
    items: [
      { id: "overview", label: "Overview", icon: Activity },
      { id: "requests", label: "Requests", icon: ScrollText },
      { id: "providers", label: "Providers", icon: Server },
      { id: "keys", label: "API keys", icon: KeyRound },
    ],
  },
  {
    label: "Build",
    items: [
      { id: "connect", label: "Connect", icon: Plug },
      { id: "playground", label: "Playground", icon: MessageSquareText },
    ],
  },
];

function Mark() {
  return (
    <svg width="22" height="22" viewBox="0 0 20 20" aria-hidden>
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

const HEALTH_LABEL = { checking: "Checking…", ok: "Gateway healthy", down: "Gateway unreachable" } as const;
const HEALTH_DOT = { checking: "warn", ok: "good", down: "bad" } as const;

export function Shell({ route, children }: { route: RouteId; children: ReactNode }) {
  const { authed, signOut, profile } = useConnection();
  const workspace = profile?.workspace.name;
  const health = useGatewayHealth(GATEWAY_URL);
  const [theme, setThemeState] = useState(currentTheme);
  const host = GATEWAY_URL.replace(/^https?:\/\//, "");

  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    setThemeState(next);
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <Mark />
          <span className="brand-name">LLMFlow</span>
        </div>

        <nav className="nav" aria-label="Primary">
          {SECTIONS.map((section) => (
            <div className="nav-section" key={section.label}>
              <div className="nav-label">{section.label}</div>
              {section.items.map(({ id, label, icon: Icon }) => (
                <a
                  key={id}
                  className="nav-item"
                  href={`#/${id}`}
                  aria-current={route === id ? "page" : undefined}
                >
                  <Icon size={16} strokeWidth={1.6} aria-hidden />
                  <span>{label}</span>
                </a>
              ))}
            </div>
          ))}
        </nav>

        <div className="sidebar-foot">
          <div className="env" title={`${GATEWAY_URL} · ${HEALTH_LABEL[health]}`}>
            <span className={`dot ${HEALTH_DOT[health]}`} aria-hidden />
            <div className="env-text">
              <span className="env-title">
                {authed && workspace ? workspace : HEALTH_LABEL[health]}
              </span>
              <span className="env-sub">{host}</span>
            </div>
          </div>

          <div className="nav-section">
            <a
              className="nav-item"
              href="#/settings"
              aria-current={route === "settings" ? "page" : undefined}
            >
              <Settings size={16} strokeWidth={1.6} aria-hidden />
              <span>Account</span>
            </a>
            <button className="nav-item" onClick={toggleTheme}>
              {theme === "dark" ? (
                <Sun size={16} strokeWidth={1.6} aria-hidden />
              ) : (
                <Moon size={16} strokeWidth={1.6} aria-hidden />
              )}
              <span>{theme === "dark" ? "Light theme" : "Dark theme"}</span>
            </button>
            {authed && (
              <button className="nav-item" onClick={() => void signOut()}>
                <LogOut size={16} strokeWidth={1.6} aria-hidden />
                <span>Sign out</span>
              </button>
            )}
          </div>
        </div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}
