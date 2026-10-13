import { render, screen } from "@testing-library/react";
import { CostAccuracy } from "./CostAccuracy";
import type { StrategyResult } from "../lib/types";

class RO {
  observe() {}
  disconnect() {}
}

const base: StrategyResult = {
  description: "",
  n: 44,
  passed: 40,
  accuracy: 0.9,
  accuracy_ci95: [0.78, 0.96],
  failures: 0,
  fallbacks: 0,
  retries: 0,
  latency_ms_mean: 500,
  latency_ms_p50: 480,
  latency_ms_p95: 900,
  prompt_tokens: 1,
  completion_tokens: 1,
  shadow_cost_usd: 0.002,
  cost_per_correct_usd: 0.00005,
  tier_mix: {},
  models_used: {},
  by_difficulty: {},
  by_category: {},
};

describe("CostAccuracy", () => {
  it("labels each strategy and distinguishes routed from fixed", () => {
    vi.stubGlobal("ResizeObserver", RO);
    render(
      <CostAccuracy
        strategies={{
          "always-large": base,
          "routed-balanced": { ...base, accuracy: 0.85, shadow_cost_usd: 0.0005 },
        }}
      />,
    );
    expect(screen.getByText("always-large")).toBeInTheDocument();
    expect(screen.getByText("routed-balanced")).toBeInTheDocument();
    expect(screen.getByText("Fixed model")).toBeInTheDocument();
  });

  it("does not crash with all-zero cost", () => {
    vi.stubGlobal("ResizeObserver", RO);
    render(<CostAccuracy strategies={{ a: { ...base, shadow_cost_usd: 0 } }} />);
    expect(screen.getByRole("img")).toBeInTheDocument();
  });
});
