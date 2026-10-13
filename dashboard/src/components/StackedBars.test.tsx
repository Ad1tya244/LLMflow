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

class RO {
  observe() {}
  disconnect() {}
}

describe("StackedBars", () => {
  beforeAll(() => {
    vi.stubGlobal("ResizeObserver", RO);
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
