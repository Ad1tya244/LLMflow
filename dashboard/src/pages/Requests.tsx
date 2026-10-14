import { ChevronDown, ChevronRight } from "lucide-react";
import { Fragment, useState } from "react";
import { Gate } from "../components/Gate";
import { EmptyState, ErrorBanner, PageHeader, Segmented, Skeleton, StatusBadge } from "../components/ui";
import { api } from "../lib/api";
import { dateTime, ms, usd } from "../lib/format";
import { useConnection } from "../lib/store";
import { useAsync } from "../lib/useAsync";

type Filter = "all" | "ok" | "error";
const PAGE = 25;

function Body() {
  const { conn } = useConnection();
  const [filter, setFilter] = useState<Filter>("all");
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<number | null>(null);
  const { data, error, loading, reload } = useAsync(
    () => api.requests(conn, PAGE, offset, filter === "all" ? undefined : filter),
    [conn, filter, offset],
    10_000,
  );

  const total = data?.total ?? 0;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(total, offset + PAGE);

  return (
    <>
      <PageHeader title="Requests" description="Every request with its routing decision, newest first.">
        <Segmented
          label="Status filter"
          value={filter}
          onChange={(v) => {
            setFilter(v);
            setOffset(0);
          }}
          options={[
            { value: "all", label: "All" },
            { value: "ok", label: "Successful" },
            { value: "error", label: "Failed" },
          ]}
        />
      </PageHeader>

      {error && <ErrorBanner message={error.message} onRetry={reload} />}
      {!data && loading && (
        <div className="panel panel-body stack">
          <Skeleton height={24} />
          <Skeleton height={24} />
          <Skeleton height={24} />
        </div>
      )}

      {data && (
        <section className={`panel ${loading ? "refetching" : ""}`}>
          {data.items.length === 0 ? (
            <EmptyState title={filter === "error" ? "No failed requests" : "No requests yet"}>
              {filter === "error"
                ? "Nothing has failed in the recorded history."
                : "Requests sent to /v1/chat/completions will be listed here."}
            </EmptyState>
          ) : (
            <>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th aria-label="Expand" />
                      <th>Time</th>
                      <th>Routed to</th>
                      <th>Status</th>
                      <th className="num">Tokens in / out</th>
                      <th className="num">Latency</th>
                      <th className="num">Shadow cost</th>
                      <th className="num">Attempts</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.items.map((r) => {
                      const expanded = open === r.id;
                      return (
                        <Fragment key={r.id}>
                          <tr
                            className="clickable"
                            onClick={() => setOpen(expanded ? null : r.id)}
                            aria-expanded={expanded}
                          >
                            <td>
                              {expanded ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}
                            </td>
                            <td className="muted">{dateTime(r.ts, true)}</td>
                            <td>
                              <div className="mono">{r.model ?? "–"}</div>
                              <div className="muted">
                                {r.provider}
                                {r.cache_status === "hit" ? " · cache hit" : ""}
                              </div>
                            </td>
                            <td>
                              <StatusBadge status={r.status} />
                            </td>
                            <td className="num">
                              {r.prompt_tokens} / {r.completion_tokens}
                            </td>
                            <td className="num">{ms(r.latency_ms)}</td>
                            <td className="num">{usd(r.shadow_cost_usd)}</td>
                            <td className="num">{r.attempts}</td>
                          </tr>
                          {expanded && (
                            <tr>
                              <td />
                              <td className="sub-row" colSpan={7}>
                                <strong>Routing:</strong> {r.route_reason || "no reason recorded"}
                                <br />
                                <strong>Requested model:</strong> <span className="mono">{r.requested_model}</span>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <div className="panel-head" style={{ borderTop: "1px solid var(--border)", borderBottom: 0 }}>
                <span className="section-note">
                  {from}–{to} of {total.toLocaleString()}
                </span>
                <div className="form-row">
                  <button className="btn" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
                    Previous
                  </button>
                  <button className="btn" disabled={to >= total} onClick={() => setOffset(offset + PAGE)}>
                    Next
                  </button>
                </div>
              </div>
            </>
          )}
        </section>
      )}
    </>
  );
}

export function Requests() {
  return (
    <div className="page">
      <Gate>
        <Body />
      </Gate>
    </div>
  );
}
