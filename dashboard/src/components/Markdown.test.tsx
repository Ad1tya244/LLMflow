import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Markdown, normaliseMath } from "./Markdown";

describe("normaliseMath", () => {
  it("converts \\( \\) and \\[ \\] to $$ and leaves code alone", () => {
    expect(normaliseMath("a \\(x^2\\) b")).toBe("a $$x^2$$ b");
    expect(normaliseMath("\\[ y = 1 \\]")).toContain("$$\ny = 1\n$$");
    const code = "```py\nprint('\\(not math\\)')\n```";
    expect(normaliseMath(code)).toBe(code);
    expect(normaliseMath("use `\\(x\\)` inline")).toBe("use `\\(x\\)` inline");
  });
  it("does not treat currency as math", () => {
    const { container } = render(<Markdown source={"It costs $5 and then $10 more."} />);
    expect(container.querySelector(".katex")).toBeNull();
    expect(container.textContent).toContain("$5 and then $10");
  });
});

describe("Markdown", () => {
  it("renders headings, lists, bold, tables and code with a copy button", () => {
    const src = [
      "## Title",
      "",
      "**Bold** and `code`",
      "",
      "1. one",
      "2. two",
      "",
      "| Model | Cost |",
      "|---|---|",
      "| 20B | low |",
      "",
      "```python",
      "print('hi')",
      "```",
    ].join("\n");
    const { container } = render(<Markdown source={src} />);
    expect(container.querySelector("h2")?.textContent).toBe("Title");
    expect(container.querySelector("strong")?.textContent).toBe("Bold");
    expect(container.querySelectorAll("ol li")).toHaveLength(2);
    expect(container.querySelectorAll("table th")).toHaveLength(2);
    expect(container.querySelector(".md-table")).not.toBeNull();
    expect(container.querySelector(".md-codeblock pre code")?.textContent?.trim()).toBe("print('hi')");
    expect(container.querySelector(".md-copy")).not.toBeNull();
    expect(container.textContent).not.toContain("##");
    expect(container.textContent).not.toContain("**");
  });

  it("renders math without leaving backslashes", () => {
    const { container } = render(<Markdown source={"Area is \\(\\pi r^2\\) and \\[ 48217 \\times 9361 \\]"} />);
    expect(container.querySelectorAll(".katex").length).toBeGreaterThanOrEqual(2);
    // the visible layer (the hidden MathML copy keeps the source for screen readers)
    const visible = [...container.querySelectorAll(".katex-html")].map((n) => n.textContent).join(" ");
    expect(visible).toContain("×");
    expect(visible).toContain("π");
    expect(visible).not.toContain("\\");
  });

  it("never renders raw HTML or javascript: links", () => {
    const { container } = render(
      <Markdown source={"<img src=x onerror=alert(1)>\n\n[click](javascript:alert(1)) and [ok](https://example.com)"} />,
    );
    expect(container.querySelector("img")).toBeNull();
    const links = [...container.querySelectorAll("a")];
    expect(links.every((a) => !a.getAttribute("href")?.startsWith("javascript:"))).toBe(true);
    const ok = links.find((a) => a.getAttribute("href") === "https://example.com");
    expect(ok?.getAttribute("rel")).toContain("noopener");
    expect(ok?.getAttribute("target")).toBe("_blank");
  });
});
