import { compact, deviceLabel, ms, niceTicks, pct, pricePerM, usd } from "./format";
import { deltaOf } from "./chat";

describe("format", () => {
  it("compacts large numbers", () => {
    expect(compact(999)).toBe("999");
    expect(compact(12_900)).toBe("12.9K");
  });
  it("formats tiny shadow costs with enough precision", () => {
    expect(usd(0)).toBe("$0.00");
    expect(usd(0.00042)).toBe("$0.00042");
    expect(usd(12.5)).toBe("$12.50");
    expect(usd(null)).toBe("–");
  });
  it("formats latency and percent", () => {
    expect(ms(412)).toBe("412 ms");
    expect(ms(1530)).toBe("1.5 s");
    expect(pct(0.0123)).toBe("1.2%");
    expect(pct(0.5)).toBe("50%");
  });
  it("produces round axis ticks starting at zero", () => {
    expect(niceTicks(0)).toEqual([0, 1]);
    const t = niceTicks(37);
    expect(t[0]).toBe(0);
    expect(t[t.length - 1]).toBeGreaterThanOrEqual(37);
    expect(t.every((v) => Number.isInteger(v))).toBe(true);
  });
});

describe("pricePerM", () => {
  it("keeps decimals stable", () => {
    expect([0.075, 0.15, 0.6, 0.29, 1.25, 0].map(pricePerM)).toEqual(["0.075", "0.15", "0.60", "0.29", "1.25", "0.00"]);
  });
});

describe("sse delta parsing", () => {
  it("extracts content and ignores [DONE] and junk", () => {
    expect(deltaOf('{"choices":[{"delta":{"content":"hi"}}]}')).toBe("hi");
    expect(deltaOf("[DONE]")).toBe("");
    expect(deltaOf("not json")).toBe("");
  });
});

describe("deviceLabel", () => {
  const cases: [string, string][] = [
    ["Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15", "Safari on macOS"],
    ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36 Edg/120.0", "Edge on Windows"],
    ["Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0", "Firefox on Linux"],
    ["Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/120 Mobile/15E148 Safari/604.1", "Chrome on iOS"],
    ["", "Unknown device"],
  ];
  it.each(cases)("labels %#", (ua, label) => {
    expect(deviceLabel(ua)).toBe(label);
  });
});
