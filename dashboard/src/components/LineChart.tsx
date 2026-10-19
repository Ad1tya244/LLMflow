import { useEffect, useMemo, useRef, useState } from "react";
import { clock, dateTime, niceTicks } from "../lib/format";

export interface LineSeries {
  label: string;
  color: string;
  values: number[];
  dashed?: boolean;
}

const M = { top: 8, right: 8, bottom: 22, left: 52 };

/** Two-or-more series over a shared time axis, with crosshair tooltip and table view. */
export function LineChart({
  times,
  series,
  bucketS,
  format,
  height = 200,
}: {
  times: number[];
  series: LineSeries[];
  bucketS: number;
  format: (v: number) => string;
  height?: number;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(640);
  const [hover, setHover] = useState<number | null>(null);
  const [table, setTable] = useState(false);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    setWidth(el.clientWidth || 640);
    const ro = new ResizeObserver(() => setWidth(el.clientWidth || 640));
    ro.observe(el);
    return () => ro.disconnect();
  }, [table]);

  const max = useMemo(() => Math.max(0, ...series.flatMap((s) => s.values)), [series]);
  const activeRows = useMemo(
    () => times.map((t, i) => ({ t, i })).filter(({ i }) => series.some((s) => (s.values[i] ?? 0) !== 0)),
    [times, series],
  );
  const hiddenCount = times.length - activeRows.length;
  const ticks = niceTicks(max, 4);
  const yMax = ticks[ticks.length - 1] ?? 1;
  const plotW = Math.max(10, width - M.left - M.right);
  const plotH = height - M.top - M.bottom;
  const n = Math.max(1, times.length);
  const x = (i: number) => M.left + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const y = (v: number) => M.top + plotH - (v / yMax) * plotH;
  const tick = bucketS >= 3600 ? dateTime : clock;
  const every = Math.max(1, Math.ceil(n / 5));

  const path = (vals: number[]) => vals.map((v, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(v)}`).join("");

  function onMove(e: React.PointerEvent<SVGRectElement>) {
    const box = e.currentTarget.getBoundingClientRect();
    const frac = (e.clientX - box.left) / box.width;
    setHover(Math.min(n - 1, Math.max(0, Math.round(frac * (n - 1)))));
  }

  function onKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowRight") setHover((h) => Math.min(n - 1, (h ?? -1) + 1));
    else if (e.key === "ArrowLeft") setHover((h) => Math.max(0, (h ?? n) - 1));
    else if (e.key === "Escape") setHover(null);
  }

  const hx = hover === null ? 0 : x(hover);
  const flip = hx > width * 0.6;

  return (
    <div>
      <div className="form-row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
        <div className="legend">
          {series.map((s) => (
            <span key={s.label}>
              <span
                className="key-line"
                style={{
                  background: s.dashed ? "transparent" : s.color,
                  borderTop: s.dashed ? `2px dashed ${s.color}` : undefined,
                  width: 14,
                }}
              />
              {s.label}
            </span>
          ))}
        </div>
        <button className="btn ghost" onClick={() => setTable((t) => !t)} aria-pressed={table}>
          {table ? "Show chart" : "Show table"}
        </button>
      </div>
      {table ? (
        <>
        <div className="table-wrap" style={{ maxHeight: height + 40, overflowY: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>Time</th>
                {series.map((s) => (
                  <th className="num" key={s.label}>
                    {s.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {activeRows.map(({ t, i }) => (
                <tr key={t}>
                  <td>{dateTime(t)}</td>
                  {series.map((s) => (
                    <td className="num" key={s.label}>
                      {format(s.values[i] ?? 0)}
                    </td>
                  ))}
                </tr>
              ))}
              {activeRows.length === 0 && (
                <tr>
                  <td colSpan={series.length + 1} className="muted">
                    No activity in this range.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {hiddenCount > 0 && activeRows.length > 0 && (
          <p className="table-note">
            {hiddenCount} empty {hiddenCount === 1 ? "interval" : "intervals"} with no activity not shown.
          </p>
        )}
        </>
      ) : (
        <div className="chart" ref={wrap}>
          <svg
            width={width}
            height={height}
            role="img"
            tabIndex={0}
            aria-label="Line chart over time. Use left and right arrow keys to read values."
            onKeyDown={onKey}
            onBlur={() => setHover(null)}
          >
            {ticks.map((t) => (
              <g key={t}>
                <line className={t === 0 ? "axis" : "grid"} x1={M.left} x2={width - M.right} y1={y(t)} y2={y(t)} />
                <text x={M.left - 8} y={y(t) + 4} textAnchor="end">
                  {format(t)}
                </text>
              </g>
            ))}
            {times.map((t, i) =>
              i % every === 0 ? (
                <text key={t} x={x(i)} y={height - 4} textAnchor="middle">
                  {tick(t)}
                </text>
              ) : null,
            )}
            {series.map((s) => (
              <path
                key={s.label}
                d={path(s.values)}
                fill="none"
                stroke={s.color}
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
                strokeDasharray={s.dashed ? "6 4" : undefined}
              />
            ))}
            {hover !== null && (
              <>
                <line className="axis" x1={hx} x2={hx} y1={M.top} y2={M.top + plotH} />
                {series.map((s) => (
                  <circle
                    key={s.label}
                    cx={hx}
                    cy={y(s.values[hover] ?? 0)}
                    r={4}
                    fill={s.color}
                    stroke="var(--surface)"
                    strokeWidth={2}
                  />
                ))}
              </>
            )}
            <rect
              x={M.left}
              y={0}
              width={plotW}
              height={height}
              fill="transparent"
              onPointerMove={onMove}
              onPointerLeave={() => setHover(null)}
            />
          </svg>
          {hover !== null && times[hover] !== undefined && (
            <div
              className="tooltip"
              role="status"
              style={{ top: 8, left: flip ? undefined : hx + 12, right: flip ? width - hx + 12 : undefined }}
            >
              <div className="t-head">{dateTime(times[hover])}</div>
              {series.map((s) => (
                <div className="t-row" key={s.label}>
                  <span>
                    <span className="key-line" style={{ background: s.color }} />
                    {s.label}
                  </span>
                  <b>{format(s.values[hover] ?? 0)}</b>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
