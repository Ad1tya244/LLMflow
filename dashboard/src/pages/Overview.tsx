import { useState } from "react";
import { Gate } from "../components/Gate";
import { GetStarted } from "../components/GetStarted";
import { LineChart } from "../components/LineChart";
import { StackedBars, type BarSeries } from "../components/StackedBars";
import {
  EmptyState,
  ErrorBanner,
  PageHeader,
  Segmented,
  Skeleton,
  StatStrip,
  TierBadge,
} from "../components/ui";
import { api } from "../lib/api";
import { compact, ms, pct, usd } from "../lib/format";
import { useConnection } from "../lib/store";
import type { RangeKey } from "../lib/types";
import { useAsync } from "../lib/useAsync";

const RANGES: { value: RangeKey; label: string }[] = [
  { value: "1h", label: "1 hour" },
  { value: "24h", label: "24 hours" },
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
];

const SERIES: BarSeries[] = [
  { key: "small", label: "Small tier", color: "var(--tier-small)" },
  { key: "medium", label: "Medium tier", color: "var(--tier-medium)" },
  { key: "large", label: "Large tier", color: "var(--tier-large)" },
  { key: "errors", label: "Errors", color: "var(--err)" },
];

function Body() {
  const { conn } = useConnection();
  const [range, setRange] = useState<RangeKey>("24h");
  const { data, error, loading, reload } = useAsync(() => api.overview(conn, range), [conn, range], 15_000);

  return (
    <>
      <PageHeader title="Overview" description="Traffic, latency and shadow cost across all routed requests.">
        <Segmented label="Time range" value={range} options={RANGES} onChange={setRange} />
      </PageHeader>

      <GetStarted />

      {error && <ErrorBanner message={error.message} onRetry={reload} />}

      {!data && loading && (
        <div className="panel panel-body stack">
          <Skeleton height={32} />
          <Skeleton height={220} />
        </div>
      )}

      {data && (
        <>
          <StatStrip
            busy={loading}
            stats={[
              { label: "Requests", value: compact(data.totals.requests), sub: `${data.totals.errors} failed` },
              { label: "Error rate", value: pct(data.totals.error_rate) },
              { label: "Tokens", value: compact(data.totals.tokens) },
              {
                label: "Shadow cost",
                value: usd(data.totals.shadow_cost_usd),
                sub: "at paid-plan list prices",
              },
              {
                label: "Saved vs. largest model",
                value: usd(data.totals.saved_vs_reference_usd),
                sub: data.totals.reference_model ? `vs. all on ${data.totals.reference_model}` : undefined,
              },
              {
                label: "Cache hit rate",
                value: data.totals.cache_hit_rate === null ? "–" : pct(data.totals.cache_hit_rate),
                sub: `${data.totals.cache_hits} of ${data.totals.cache_lookups} cacheable`,
              },
              { label: "Latency p50", value: ms(data.totals.p50_latency_ms) },
              { label: "Latency p95", value: ms(data.totals.p95_latency_ms) },
            ]}
          />

          {data.totals.requests === 0 ? (
            <div className="panel">
              <EmptyState
                title="No requests in this range"
                action={
                  <pre className="codeblock">{`curl ${conn.baseUrl}/v1/chat/completions \\
  -H "Authorization: Bearer $LLMFLOW_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"model":"auto","messages":[{"role":"user","content":"Hello"}]}'`}</pre>
                }
              >
                Send a request through the gateway and it will appear here within seconds. Point any
                OpenAI SDK at the gateway and use <code>model: "auto"</code>.
              </EmptyState>
            </div>
          ) : (
            <>
              <section className={`panel ${loading ? "refetching" : ""}`}>
                <div className="panel-head">
                  <h2 className="section-title">Requests by model tier</h2>
                  <span className="section-note">Routed tier per request</span>
                </div>
                <div className="panel-body">
                  <StackedBars points={data.series} series={SERIES} bucketS={data.bucket_s} />
                </div>
              </section>

              <section className={`panel ${loading ? "refetching" : ""}`}>
                <div className="panel-head">
                  <h2 className="section-title">Shadow cost over time</h2>
                  <span className="section-note">
                    Actual routing vs. sending every request to {data.totals.reference_model ?? "the top model"}
                  </span>
                </div>
                <div className="panel-body">
                  <LineChart
                    times={data.series.map((p) => p.ts)}
                    bucketS={data.bucket_s}
                    format={usd}
                    series={[
                      {
                        label: "Reference (always top model)",
                        color: "var(--text-3)",
                        dashed: true,
                        values: data.series.map((p) => p.reference_cost_usd),
                      },
                      {
                        label: "Actual (routed)",
                        color: "var(--accent)",
                        values: data.series.map((p) => p.shadow_cost_usd),
                      },
                    ]}
                  />
                </div>
              </section>

              <section className={`panel ${loading ? "refetching" : ""}`}>
                <div className="panel-head">
                  <h2 className="section-title">Models</h2>
                  <span className="section-note">Successful requests in range</span>
                </div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Model</th>
                        <th>Tier</th>
                        <th className="num">Requests</th>
                        <th className="num">Tokens</th>
                        <th className="num">Shadow cost</th>
                        <th className="num">p50 latency</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.by_model.map((m) => (
                        <tr key={m.model}>
                          <td>
                            <span className="mono">{m.model}</span>{" "}
                            <span className="muted">{m.provider}</span>
                          </td>
                          <td>
                            <TierBadge tier={m.tier} />
                          </td>
                          <td className="num">{m.requests.toLocaleString()}</td>
                          <td className="num">{compact(m.tokens)}</td>
                          <td className="num">{usd(m.shadow_cost_usd)}</td>
                          <td className="num">{ms(m.p50_latency_ms)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}
        </>
      )}
    </>
  );
}

export function Overview() {
  return (
    <div className="page">
      <Gate>
        <Body />
      </Gate>
    </div>
  );
}
