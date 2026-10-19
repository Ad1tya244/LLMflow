import { fireEvent, render, screen } from "@testing-library/react";
import { LineChart } from "./LineChart";

const observed: Element[] = [];
class RO {
  observe(el: Element) {
    observed.push(el);
  }
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

  it("measures the chart again after switching to the table and back", () => {
    const { container } = render(<LineChart {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Show table" }));
    fireEvent.click(screen.getByRole("button", { name: "Show chart" }));
    const chart = container.querySelector(".chart");
    expect(chart).not.toBeNull();
    expect(observed[observed.length - 1]).toBe(chart);
  });

  it("table view hides intervals where every series is zero", () => {
    render(
      <LineChart
        {...props}
        times={[1_700_000_000, 1_700_001_800, 1_700_003_600]}
        series={[
          { label: "Reference", color: "gray", values: [0, 0, 6], dashed: true },
          { label: "Actual", color: "blue", values: [0, 0, 2] },
        ]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Show table" }));
    expect(screen.getAllByRole("row")).toHaveLength(2); // header + the active interval
    expect(screen.getByText("2 empty intervals with no activity not shown.")).toBeInTheDocument();
  });

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
