import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Markdown } from "./Markdown";

describe("Markdown", () => {
  it("renders lists, bold, code and never injects HTML", () => {
    const { container } = render(
      <Markdown source={"**Hi** `x`\n\n- a\n- b\n\n```\ncode <b>\n```\n<img src=x onerror=alert(1)>"} />,
    );
    expect(container.querySelectorAll("li")).toHaveLength(2);
    expect(container.querySelector("strong")?.textContent).toBe("Hi");
    expect(container.querySelector("pre")?.textContent).toBe("code <b>");
    expect(container.querySelector("img")).toBeNull();
  });
});
