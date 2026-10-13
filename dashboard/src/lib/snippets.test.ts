import { buildSnippets } from "./snippets";

describe("buildSnippets", () => {
  it("points every snippet at the gateway's /v1 and never contains a real key", () => {
    const all = buildSnippets("https://gw.example.com/");
    expect(all.map((s) => s.id)).toEqual(["env", "python", "node", "curl"]);
    for (const s of all) {
      expect(s.code).toContain("https://gw.example.com/v1");
      expect(s.code).toContain("<YOUR_LLMFLOW_API_KEY>");
      expect(s.code).not.toContain("//v1");
    }
  });
});
