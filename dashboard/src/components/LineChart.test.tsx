import { fireEvent, render, screen } from "@testing-library/react";
import { LineChart } from "./LineChart";

class RO {
  observe() {}
  disconnect() {}
}

describe("LineChart", () => {
  beforeAll(() => {
    vi.stubGlobal("ResizeObserver", RO);
  });

  const props = {
    times: [1_700_000_000, 1_700_001_800],
    bucketS: 1800,
    format: (v: number) => `$${v}`,
    series: [
      { label: "Reference", color: "gray", values: [4, 8], dashed: true },
      { label: "Actual", color: "blue", values: [1, 2] },
    ],
  };

  it("lists every series value in the table view", () => {
    render(<LineChart {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Show table" }));
    expect(screen.getAllByRole("row")).toHaveLength(3);
    expect(screen.getByText("$8")).toBeInTheDocument();
  });

  it("reads values by keyboard", () => {
    render(<LineChart {...props} />);
    fireEvent.keyDown(screen.getByRole("img"), { key: "ArrowRight" });
    expect(screen.getByRole("status")).toHaveTextContent("$4");
  });
});
