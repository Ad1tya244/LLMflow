import { act, render, screen, waitFor } from "@testing-library/react";
import { api, request } from "./api";
import { ConnectionProvider, useConnection } from "./store";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  sessionStorage.clear();
});

describe("cookie-session requests", () => {
  it("sends credentials and the CSRF header, never an Authorization header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json(200, { ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    await request({ baseUrl: "http://gw", csrf: "csrf-123" }, "/account");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://gw/account");
    expect(init.credentials).toBe("include");
    const headers = init.headers as Record<string, string>;
    expect(headers["X-LLMFlow-CSRF"]).toBe("csrf-123");
    expect(Object.keys(headers).map((h) => h.toLowerCase())).not.toContain("authorization");
  });

  it("surfaces the server's message for a failed sign-in without echoing the password", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(json(401, { error: { type: "authentication_error", message: "invalid email or password" } })),
    );
    const err = await api.login("http://gw", "a@example.com", "hunter2-hunter2").catch((e: Error) => e);
    expect(err).toBeInstanceOf(Error);
    expect((err as Error).message).toBe("invalid email or password");
    expect((err as Error).message).not.toContain("hunter2");
  });

  it("maps the server's csrf_token for both login and sign-up", async () => {
    const profile = { workspace: { id: "t_1", name: "Acme" }, user: { email: "a@example.com" } };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async () =>
        json(201, { ...profile, csrf_token: "tok-1", api_key: "llmf_x", recovery_codes: ["AAAA-BBBB-CCCC"] }),
      ),
    );
    const logged = await api.login("http://gw", "a@example.com", "pw-pw-pw-pw-pw");
    expect("csrf" in logged && logged.csrf).toBe("tok-1");
    const signed = await api.signup("http://gw", "a@example.com", "pw-pw-pw-pw-pw", "Acme", "");
    expect(signed.csrf).toBe("tok-1");
    expect(signed.api_key).toBe("llmf_x");
    expect(signed.recovery_codes).toHaveLength(1);
  });

  it("returns an MFA challenge instead of a session when a second factor is required", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async () => json(200, { mfa_required: true, mfa_token: "challenge-1" })),
    );
    const r = await api.login("http://gw", "a@example.com", "pw-pw-pw-pw-pw");
    expect(r).toEqual({ mfaToken: "challenge-1" });
  });

  it("treats a signed-out probe as null, not an error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(200, { authenticated: false })));
    expect(await api.currentSession("http://gw")).toBeNull();
  });
});

describe("ConnectionProvider", () => {
  function Probe() {
    const { auth, signIn, conn, profile } = useConnection();
    return (
      <div>
        <span data-testid="auth">{auth}</span>
        <span data-testid="csrf">{conn.csrf}</span>
        <span data-testid="who">{profile?.user.email}</span>
        <button onClick={() => void signIn("a@example.com", "my-secret-passphrase")}>go</button>
      </div>
    );
  }

  it("never writes credentials to web storage and removes legacy keys", async () => {
    sessionStorage.setItem("llmflow.apiKey", "old-stored-key");
    localStorage.setItem("llmflow.baseUrl", "http://evil.example");
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/auth/login") && init?.method === "POST") {
        return json(200, {
          csrf_token: "csrf-abc",
          workspace: { id: "t_1", name: "Acme" },
          user: { email: "a@example.com" },
        });
      }
      return json(200, { authenticated: false });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <ConnectionProvider>
        <Probe />
      </ConnectionProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("auth")).toHaveTextContent("signed_out"));
    expect(sessionStorage.getItem("llmflow.apiKey")).toBeNull();
    expect(localStorage.getItem("llmflow.baseUrl")).toBeNull();

    await act(async () => {
      screen.getByText("go").click();
    });
    await waitFor(() => expect(screen.getByTestId("auth")).toHaveTextContent("signed_in"));
    expect(screen.getByTestId("who")).toHaveTextContent("a@example.com");
    // the CSRF token the server issued must be the one used on later requests
    expect(screen.getByTestId("csrf")).toHaveTextContent("csrf-abc");

    const everything = JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage });
    for (const secret of ["my-secret-passphrase", "csrf-abc"]) expect(everything).not.toContain(secret);
  });
});
