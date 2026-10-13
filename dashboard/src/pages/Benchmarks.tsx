import { useState } from "react";
import { CostAccuracy } from "../components/CostAccuracy";
import { Gate } from "../components/Gate";
import { EmptyState, ErrorBanner, PageHeader, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { ms, usd } from "../lib/format";
import { useConnection } from "../lib/store";
import type { StrategyResult } from "../lib/types";
import { useAsync } from "../lib/useAsync";

const signed = (v: number | null | undefined, unit: string, digits = 0) =>
  v === null || v === undefined ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(digits)}${unit}`;

function order(names: string[]): string[] {
  return [...names].sort((a, b) => {
    const ra = a.startsWith("routed") ? 1 : 0;
    const rb = b.startsWith("routed") ? 1 : 0;
    return ra - rb || a.localeCompare(b);
  });
}

function Body() {
  const { conn } = useConnection();
  const [name, setName] = useState<string | undefined>();
  const { data, error, loading, reload } = useAsync(() => api.benchmarks(conn, name), [conn, name]);

  return (
    <>
      <PageHeader
        title="Benchmarks"
        description="Routed vs. fixed-model strategies on a checkable suite. Measured with real Groq calls."
      >
        {data && data.available.length > 1 && (
          <select
            className="select"
            style={{ width: "auto" }}
            aria-label="Benchmark run"
            value={data.selected ?? ""}
            onChange={(e) => setName(e.target.value)}
          >
            {data.available.map((a) => (
              <option key={a}>{a}</option>
            ))}
          </select>
        )}
      </PageHeader>

      {error && <ErrorBanner message={error.message} onRetry={reload} />}
      {!data && loading && (
        <div className="panel panel-body stack">
          <Skeleton height={24} />
          <Skeleton height={240} />
        </div>
      )}

      {data && !data.report && (
        <div className="panel">
          <EmptyState title="No benchmark results yet">
            Run the benchmark from the project root. It is paced to the provider's free-tier limits and
            can be resumed.
            <pre className="codeblock">npm run bench</pre>
          </EmptyState>
        </div>
      )}

      {data?.report && (
        <>
          <div className="banner" role="note">
            <span className="badge good">MEASURED</span>
            <div className="grow">
              {data.report.items} hand-written items, deterministic checks, no LLM judge · generated{" "}
              {data.report.generated_at.slice(0, 10)} · shadow cost is tokens × paid list price (actual spend
              was zero). The suite is small, so differences under ~15 points are within noise.
              {(data.report.notes ?? []).map((n) => (
                <div key={n} className="muted" style={{ marginTop: 4 }}>
                  Note: {n}
                </div>
              ))}
            </div>
          </div>

          <section className="panel">
            <div className="panel-head">
              <h2 className="section-title">Accuracy vs. cost</h2>
              <span className="section-note">Up and to the left is better</span>
            </div>
            <div className="panel-body">
              <CostAccuracy strategies={data.report.strategies} />
            </div>
          </section>

          <section className="panel">
            <div className="panel-head">
              <h2 className="section-title">Strategies</h2>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Strategy</th>
                    <th className="num">Accuracy (95% interval)</th>
                    <th className="num">Failures</th>
                    <th className="num">p50 latency</th>
                    <th className="num">Shadow cost</th>
                    <th className="num">Cost / correct</th>
                    <th className="num">Cost vs. large</th>
                    <th className="num">Accuracy vs. large</th>
                  </tr>
                </thead>
                <tbody>
                  {order(Object.keys(data.report.strategies)).map((n) => {
                    const s = data.report?.strategies[n] as StrategyResult;
                    return (
                      <tr key={n}>
                        <td>
                          <div className="mono">{n}</div>
                          <div className="muted">{s.description}</div>
                        </td>
                        <td className="num">
                          {(s.accuracy * 100).toFixed(0)}%{" "}
                          <span className="muted">
                            ({(s.accuracy_ci95[0] * 100).toFixed(0)}–{(s.accuracy_ci95[1] * 100).toFixed(0)})
                          </span>
                        </td>
                        <td className="num">{s.failures}</td>
                        <td className="num">{ms(s.latency_ms_p50)}</td>
                        <td className="num">{usd(s.shadow_cost_usd)}</td>
                        <td className="num">{usd(s.cost_per_correct_usd)}</td>
                        <td className="num">
                          {s.cost_saving_vs_large_pct === null || s.cost_saving_vs_large_pct === undefined
                            ? "–"
                            : signed(-s.cost_saving_vs_large_pct, "%")}
                        </td>
                        <td className="num">{signed(s.accuracy_delta_vs_large_pts, " pts", 1)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          <div className="split-even">
            <section className="panel">
              <div className="panel-head">
                <h2 className="section-title">Accuracy by difficulty</h2>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Strategy</th>
                      <th className="num">Easy</th>
                      <th className="num">Medium</th>
                      <th className="num">Hard</th>
                    </tr>
                  </thead>
                  <tbody>
                    {order(Object.keys(data.report.strategies)).map((n) => {
                      const d = data.report?.strategies[n]?.by_difficulty ?? {};
                      return (
                        <tr key={n}>
                          <td className="mono">{n}</td>
                          {["easy", "medium", "hard"].map((k) => (
                            <td className="num" key={k}>
                              {d[k] ? `${(d[k].accuracy * 100).toFixed(0)}%` : "–"}
                              {d[k] && <span className="muted"> n={d[k].n}</span>}
                            </td>
                          ))}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="panel">
              <div className="panel-head">
                <h2 className="section-title">Where routed traffic went</h2>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Strategy</th>
                      <th className="num">Small</th>
                      <th className="num">Medium</th>
                      <th className="num">Large</th>
                    </tr>
                  </thead>
                  <tbody>
                    {order(Object.keys(data.report.strategies))
                      .filter((n) => n.startsWith("routed"))
                      .map((n) => {
                        const mix = data.report?.strategies[n]?.tier_mix ?? {};
                        return (
                          <tr key={n}>
                            <td className="mono">{n}</td>
                            <td className="num">{mix.small ?? 0}</td>
                            <td className="num">{mix.medium ?? 0}</td>
                            <td className="num">{mix.large ?? 0}</td>
                          </tr>
                        );
                      })}
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        </>
      )}
    </>
  );
}

export function Benchmarks() {
  return (
    <div className="page">
      <Gate>
        <Body />
      </Gate>
    </div>
  );
}
