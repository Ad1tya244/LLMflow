import { fireEvent, render, screen } from "@testing-library/react";
import { StackedBars, type BarSeries } from "./StackedBars";
import type { SeriesPoint } from "../lib/types";

const point = (ts: number, small: number, large: number): SeriesPoint => ({
  ts,
  requests: small + large,
  errors: 0,
  tokens: 0,
  shadow_cost_usd: 0,
  reference_cost_usd: 0,
  small,
  medium: 0,
  large,
});

const SERIES: BarSeries[] = [
  { key: "small", label: "Small tier", color: "red" },
  { key: "large", label: "Large tier", color: "blue" },
];

const observed: Element[] = [];
class RO {
  observe(el: Element) {
    observed.push(el);
  }
  disconnect() {}
}

describe("StackedBars", () => {
  beforeAll(() => {
    vi.stubGlobal("ResizeObserver", RO);
  });

  it("measures the chart again after switching to the table and back", () => {
    const { container } = render(<StackedBars points={[point(1_700_000_000, 3, 2)]} series={SERIES} bucketS={1800} />);
    fireEvent.click(screen.getByRole("button", { name: "Show table" }));
    fireEvent.click(screen.getByRole("button", { name: "Show chart" }));
    const chart = container.querySelector(".chart");
    expect(chart).not.toBeNull();
    expect(observed[observed.length - 1]).toBe(chart); // the NEW chart element is being observed
  });

  it("table view hides empty intervals and says how many", () => {
    const pts = [point(1_700_000_000, 0, 0), point(1_700_001_800, 0, 0), point(1_700_003_600, 3, 1), point(1_700_005_400, 0, 0)];
    render(<StackedBars points={pts} series={SERIES} bucketS={1800} />);
    fireEvent.click(screen.getByRole("button", { name: "Show table" }));
    expect(screen.getAllByRole("row")).toHaveLength(2); // header + the one interval with activity
    expect(screen.getByText("3 empty intervals with no activity not shown.")).toBeInTheDocument();
  });

  it("table view says so when the whole range is empty", () => {
    render(<StackedBars points={[point(1_700_000_000, 0, 0), point(1_700_001_800, 0, 0)]} series={SERIES} bucketS={1800} />);
    fireEvent.click(screen.getByRole("button", { name: "Show table" }));
    expect(screen.getByText("No activity in this range.")).toBeInTheDocument();
    expect(screen.queryByText(/not shown/)).toBeNull();
  });

  it("renders a legend and offers a table view with every value", () => {
    render(<StackedBars points={[point(1_700_000_000, 3, 2), point(1_700_001_800, 0, 5)]} series={SERIES} bucketS={1800} />);
    expect(screen.getByText("Small tier")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show table" }));
    const rows = screen.getAllByRole("row");
    expect(rows).toHaveLength(3); // header + 2 points
    expect(screen.getAllByText("5").length).toBeGreaterThan(0);
  });

  it("shows tooltip values via keyboard", () => {
    render(<StackedBars points={[point(1_700_000_000, 3, 2)]} series={SERIES} bucketS={1800} />);
    const chart = screen.getByRole("img");
    fireEvent.keyDown(chart, { key: "ArrowRight" });
    expect(screen.getByRole("status")).toHaveTextContent("3");
  });
});
