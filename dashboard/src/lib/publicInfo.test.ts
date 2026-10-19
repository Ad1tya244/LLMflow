import { api, describeGateway } from "./api";

afterEach(() => vi.unstubAllGlobals());

describe("publicInfo failure messages", () => {
  it("names the host when the browser cannot connect at all", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(api.publicInfo("https://llmflow-gateway.vercel.app/gw")).rejects.toThrow(
      /could not connect to llmflow-gateway\.vercel\.app\/gw.*blocker/,
    );
  });

  it("reports the HTTP status when the gateway answers with an error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("bad gateway", { status: 502 })));
    await expect(api.publicInfo("http://localhost:8000")).rejects.toThrow(
      /localhost:8000 answered with HTTP 502.*starting up/,
    );
  });

  it("reports an unreadable reply", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>not json</html>", { status: 200 })));
    await expect(api.publicInfo("http://localhost:8000")).rejects.toThrow(/could not read/);
  });

  it("returns the facts on success", async () => {
    const body = { byok_enabled: true, signup_enabled: true, invite_code_required: false, password_min_length: 12 };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 200 })));
    await expect(api.publicInfo("http://localhost:8000")).resolves.toEqual(body);
  });

  it("describes the gateway without scheme or trailing slashes", () => {
    expect(describeGateway("https://example.com/gw/")).toBe("example.com/gw");
    expect(describeGateway("")).toBe("the gateway");
  });
});
