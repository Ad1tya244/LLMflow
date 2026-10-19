import { pageUrlForAnalytics } from "./analytics";

describe("pageUrlForAnalytics", () => {
  it("keeps the origin and path and drops the hash route", () => {
    expect(pageUrlForAnalytics("https://llmflow-gateway.vercel.app/#/providers")).toBe(
      "https://llmflow-gateway.vercel.app/",
    );
  });

  it("drops query strings and tokens in the fragment", () => {
    expect(pageUrlForAnalytics("https://x.app/verify?token=secret#token=also-secret")).toBe("https://x.app/verify");
    expect(pageUrlForAnalytics("https://x.app/#/reset?token=abc123")).toBe("https://x.app/");
  });

  it("never leaks a query or fragment even for a malformed URL", () => {
    expect(pageUrlForAnalytics("not a url?token=abc#frag")).toBe("not a url");
    expect(pageUrlForAnalytics("")).toBe("");
  });
});
