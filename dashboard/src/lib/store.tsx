import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api, onUnauthorized, type Connection, type Profile, type SessionInfo } from "./api";

const LEGACY_KEYS = ["llmflow.apiKey", "llmflow.baseUrl"];
const DEFAULT_URL = "http://localhost:8000";

export type AuthState = "checking" | "signed_out" | "signed_in";

/** The gateway is fixed per deployment (build-time), never typed by the user. */
export const GATEWAY_URL: string = resolveGatewayUrl(
  (import.meta.env.VITE_GATEWAY_URL as string | undefined) || DEFAULT_URL,
);

/** A leading "/" means "same site, behind a reverse-proxy path" (e.g. ``/gw`` on Vercel), which
 *  keeps the session cookie first-party. Resolve it to a full URL so snippets stay copy-pasteable. */
export function resolveGatewayUrl(raw: string, origin = window.location.origin): string {
  const full = raw.startsWith("/") ? `${origin}${raw}` : raw;
  return full.replace(/\/+$/, "");
}

interface ConnectionState {
  conn: Connection;
  auth: AuthState;
  authed: boolean;
  profile: Profile | null;
  /** Resolves to ``{ mfaToken }`` when a second factor is still needed. */
  signIn: (email: string, password: string) => Promise<{ mfaToken: string } | null>;
  signInMfa: (mfaToken: string, code: string) => Promise<void>;
  /** After sign-up the session is already established; this adopts it. */
  adopt: (info: SessionInfo) => void;
  signOut: () => Promise<void>;
}

const Ctx = createContext<ConnectionState | null>(null);

/**
 * Holds an in-memory CSRF token and the signed-in profile. The credential is an HttpOnly
 * cookie managed by the browser; nothing secret is kept in web storage.
 */
export function ConnectionProvider({ children }: { children: ReactNode }) {
  const [csrf, setCsrf] = useState("");
  const [profile, setProfile] = useState<Profile | null>(null);
  const [auth, setAuth] = useState<AuthState>("checking");
  const started = useRef(false);

  const adopt = useCallback((info: SessionInfo) => {
    setCsrf(info.csrf);
    setProfile({ workspace: info.workspace, user: info.user });
    setAuth("signed_in");
  }, []);

  const clear = useCallback(() => {
    setCsrf("");
    setProfile(null);
    setAuth("signed_out");
  }, []);

  useEffect(() => {
    try {
      for (const k of LEGACY_KEYS) {
        sessionStorage.removeItem(k);
        localStorage.removeItem(k);
      }
    } catch {
      /* storage unavailable */
    }
    if (started.current) return;
    started.current = true;
    void api.currentSession(GATEWAY_URL).then((info) => (info ? adopt(info) : clear()));
  }, [adopt, clear]);

  useEffect(() => {
    onUnauthorized(clear);
    return () => onUnauthorized(null);
  }, [clear]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const r = await api.login(GATEWAY_URL, email, password);
      if ("mfaToken" in r) return r;
      adopt(r);
      return null;
    },
    [adopt],
  );

  const signInMfa = useCallback(
    async (mfaToken: string, code: string) => {
      adopt(await api.loginMfa(GATEWAY_URL, mfaToken, code));
    },
    [adopt],
  );

  const signOut = useCallback(async () => {
    try {
      await api.logout({ baseUrl: GATEWAY_URL, csrf });
    } finally {
      clear();
    }
  }, [csrf, clear]);

  const value = useMemo<ConnectionState>(
    () => ({
      conn: { baseUrl: GATEWAY_URL, csrf },
      auth,
      authed: auth === "signed_in",
      profile,
      signIn,
      signInMfa,
      adopt,
      signOut,
    }),
    [csrf, auth, profile, signIn, signInMfa, adopt, signOut],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useConnection(): ConnectionState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useConnection must be used inside ConnectionProvider");
  return ctx;
}
