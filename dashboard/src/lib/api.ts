import type {
  AccountInfo,
  ApiKeyInfo,
  AuditEvent,
  Overview,
  PublicInfo,
  RangeKey,
  RequestPage,
  SessionRow,
  WorkspaceSettings,
} from "./types";

/** ``csrf`` is held in memory only; the session itself is an HttpOnly cookie. */
export interface Connection {
  baseUrl: string;
  csrf: string;
}

export interface Profile {
  workspace: { id: string; name: string };
  user: { email: string };
}

export interface SessionInfo extends Profile {
  csrf: string;
}

export interface SignupResult extends SessionInfo {
  api_key: string;
  recovery_codes: string[];
}

/** Short, human label for where requests go, e.g. "llm-flow-live.vercel.app/gw". */
export function describeGateway(baseUrl: string): string {
  return baseUrl.replace(/^https?:\/\//, "").replace(/\/+$/, "") || "the gateway";
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly kind: string,
  ) {
    super(message);
  }
}

let unauthorizedHandler: (() => void) | null = null;

/** Lets the app react when the server says the session is no longer valid. */
export function onUnauthorized(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

function join(base: string, path: string): string {
  return `${base.replace(/\/+$/, "")}${path}`;
}

export async function toError(res: Response): Promise<ApiError> {
  let message = `Request failed with status ${res.status}`;
  let kind = "http_error";
  try {
    const body = (await res.json()) as { error?: { message?: string; type?: string } };
    if (body.error?.message) message = body.error.message;
    if (body.error?.type) kind = body.error.type;
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(message, res.status, kind);
}

async function send(
  baseUrl: string,
  path: string,
  init: RequestInit,
  csrf?: string,
): Promise<Response> {
  try {
    return await fetch(join(baseUrl, path), {
      ...init,
      credentials: "include",
      headers: {
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...(csrf ? { "X-LLMFlow-CSRF": csrf } : {}),
        ...init.headers,
      },
    });
  } catch {
    // fetch only throws before any response: the server is down, still starting, or the browser
    // blocked the request (for example a CORS policy that does not allow the method).
    throw new ApiError(
      "The request did not reach the gateway. It may be starting up, or the browser blocked it; " +
        "if this persists, check that the API is running and allows this dashboard's origin.",
      0,
      "network",
    );
  }
}

/** Authenticated JSON request. A 401 signs the user out of the UI. */
export async function request<T>(c: Connection, path: string, init: RequestInit = {}): Promise<T> {
  const res = await send(c.baseUrl, path, init, c.csrf);
  if (!res.ok) {
    if (res.status === 401) unauthorizedHandler?.();
    throw await toError(res);
  }
  return (await res.json()) as T;
}

async function publicJson<T>(baseUrl: string, path: string, body: unknown): Promise<T> {
  const res = await send(baseUrl, path, { method: "POST", body: JSON.stringify(body) });
  if (!res.ok) throw await toError(res);
  return (await res.json()) as T;
}

interface ServerSession extends Profile {
  csrf_token: string;
}

/** The server names the token ``csrf_token``; the client uses ``csrf`` everywhere. */
function toSession(s: ServerSession): SessionInfo {
  return { csrf: s.csrf_token, workspace: s.workspace, user: s.user };
}

export const api = {
  // --- people -----------------------------------------------------------------------
  signup: async (
    baseUrl: string,
    email: string,
    password: string,
    workspaceName: string,
    inviteCode: string,
  ): Promise<SignupResult> => {
    const r = await publicJson<ServerSession & { api_key: string; recovery_codes: string[] }>(
      baseUrl,
      "/auth/signup",
      { email, password, workspace_name: workspaceName, invite_code: inviteCode },
    );
    return { ...toSession(r), api_key: r.api_key, recovery_codes: r.recovery_codes };
  },
  /** Either a session, or ``{ mfaToken }`` when a second factor is required. */
  login: async (
    baseUrl: string,
    email: string,
    password: string,
  ): Promise<SessionInfo | { mfaToken: string }> => {
    const r = await publicJson<ServerSession | { mfa_required: true; mfa_token: string }>(
      baseUrl,
      "/auth/login",
      { email, password },
    );
    return "mfa_required" in r ? { mfaToken: r.mfa_token } : toSession(r);
  },
  loginMfa: async (baseUrl: string, mfaToken: string, code: string): Promise<SessionInfo> =>
    toSession(await publicJson<ServerSession>(baseUrl, "/auth/login/mfa", { mfa_token: mfaToken, code })),
  mfaSetup: (c: Connection, password: string) =>
    request<{ secret: string; otpauth_uri: string }>(c, "/auth/mfa/setup", {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
  mfaEnable: (c: Connection, code: string) =>
    request<{ status: string }>(c, "/auth/mfa/enable", { method: "POST", body: JSON.stringify({ code }) }),
  mfaDisable: (c: Connection, password: string, code: string) =>
    request<{ status: string }>(c, "/auth/mfa/disable", {
      method: "POST",
      body: JSON.stringify({ password, code }),
    }),
  recover: (baseUrl: string, email: string, recoveryCode: string, newPassword: string) =>
    publicJson<{ status: string; recovery_codes_left: number }>(baseUrl, "/auth/recover", {
      email,
      recovery_code: recoveryCode,
      new_password: newPassword,
    }),
  /** Existing session info, or null when signed out. */
  currentSession: async (baseUrl: string): Promise<SessionInfo | null> => {
    try {
      const res = await send(baseUrl, "/auth/session", {});
      if (!res.ok) return null;
      const body = (await res.json()) as Partial<SessionInfo> & { authenticated: boolean; csrf_token?: string };
      if (!body.authenticated || !body.csrf_token || !body.workspace || !body.user) return null;
      return { csrf: body.csrf_token, workspace: body.workspace, user: body.user };
    } catch {
      return null;
    }
  },
  logout: async (c: Connection) => {
    await send(c.baseUrl, "/auth/logout", { method: "POST" }, c.csrf);
  },
  /** Public gateway facts for the sign-in screen. Throws an ApiError that says what failed. */
  publicInfo: async (baseUrl: string): Promise<PublicInfo> => {
    const where = describeGateway(baseUrl);
    let res: Response;
    try {
      res = await send(baseUrl, "/public/info", {});
    } catch {
      throw new ApiError(
        `The browser could not connect to ${where}. Check your internet connection, and whether an ad blocker, VPN or network filter is blocking it.`,
        0,
        "network",
      );
    }
    if (!res.ok) {
      throw new ApiError(
        `${where} answered with HTTP ${res.status}. The service may be starting up or restarting; try again in a minute.`,
        res.status,
        "unavailable",
      );
    }
    try {
      return (await res.json()) as PublicInfo;
    } catch {
      throw new ApiError(`${where} sent a reply this page could not read.`, res.status, "bad_response");
    }
  },
  health: async (baseUrl: string) => {
    const res = await send(baseUrl, "/healthz", {});
    if (!res.ok) throw await toError(res);
  },

  // --- workspace --------------------------------------------------------------------
  account: (c: Connection) => request<AccountInfo>(c, "/account"),
  overview: (c: Connection, range: RangeKey) => request<Overview>(c, `/account/overview?range=${range}`),
  requests: (c: Connection, limit: number, offset: number, status?: "ok" | "error") =>
    request<RequestPage>(
      c,
      `/account/requests?limit=${limit}&offset=${offset}${status ? `&status=${status}` : ""}`,
    ),
  settings: (c: Connection) => request<WorkspaceSettings>(c, "/account/settings"),
  saveSettings: (c: Connection, s: Omit<WorkspaceSettings, "platform_caps">) =>
    request<WorkspaceSettings>(c, "/account/settings", { method: "PUT", body: JSON.stringify(s) }),
  sessions: (c: Connection) => request<{ sessions: SessionRow[] }>(c, "/account/sessions"),
  revokeSession: (c: Connection, id: string) =>
    request<{ status: string }>(c, `/account/sessions/${encodeURIComponent(id)}`, { method: "DELETE" }),
  revokeOtherSessions: (c: Connection) =>
    request<{ revoked: number }>(c, "/account/sessions/revoke-others", { method: "POST" }),
  deleteWorkspace: (c: Connection, password: string, confirmName: string) =>
    request<{ status: string }>(c, "/auth/workspace", {
      method: "DELETE",
      body: JSON.stringify({ password, confirm_name: confirmName }),
    }),
  audit: (c: Connection) => request<{ events: AuditEvent[] }>(c, "/account/audit"),
  apiKeys: (c: Connection) => request<{ keys: ApiKeyInfo[] }>(c, "/account/api-keys"),
  revealApiKey: (c: Connection, id: string, password: string, code?: string) =>
    request<{ api_key: string }>(c, `/account/api-keys/${encodeURIComponent(id)}/reveal`, {
      method: "POST",
      body: JSON.stringify({ password, ...(code ? { code } : {}) }),
    }),
  revealProviderKey: (c: Connection, provider: string, password: string, code?: string) =>
    request<{ api_key: string }>(c, `/account/provider-keys/${encodeURIComponent(provider)}/reveal`, {
      method: "POST",
      body: JSON.stringify({ password, ...(code ? { code } : {}) }),
    }),
  createApiKey: (c: Connection, name: string) =>
    request<ApiKeyInfo & { api_key: string }>(c, "/account/api-keys", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  revokeApiKey: (c: Connection, id: string) =>
    request<{ status: string }>(c, `/account/api-keys/${encodeURIComponent(id)}`, { method: "DELETE" }),
  putProviderKey: (c: Connection, provider: string, apiKey: string) =>
    request<{ provider: string; last4: string; verified: boolean | null }>(
      c,
      `/account/provider-keys/${encodeURIComponent(provider)}`,
      { method: "PUT", body: JSON.stringify({ api_key: apiKey }) },
    ),
  deleteProviderKey: (c: Connection, provider: string, password: string, code?: string) =>
    request<{ status: string }>(c, `/account/provider-keys/${encodeURIComponent(provider)}`, {
      method: "DELETE",
      body: JSON.stringify({ password, ...(code ? { code } : {}) }),
    }),
  pauseProviderKey: (c: Connection, provider: string, paused: boolean) =>
    request<{ provider: string; paused: boolean }>(
      c,
      `/account/provider-keys/${encodeURIComponent(provider)}/pause`,
      { method: "PUT", body: JSON.stringify({ paused }) },
    ),
  changePassword: (c: Connection, currentPassword: string, newPassword: string) =>
    request<{ status: string }>(c, "/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    }),
  regenerateRecoveryCodes: (c: Connection, password: string) =>
    request<{ recovery_codes: string[] }>(c, "/auth/recovery-codes", {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
};
