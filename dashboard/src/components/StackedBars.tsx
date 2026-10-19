import { useEffect, useMemo, useRef, useState } from "react";
import { clock, compact, dateTime, niceTicks } from "../lib/format";
import type { SeriesPoint } from "../lib/types";

export interface BarSeries {
  key: keyof SeriesPoint;
  label: string;
  color: string;
}

const dayLabel = (t: number) =>
  new Date(t * 1000).toLocaleDateString("en", { month: "short", day: "numeric" });

const M = { top: 8, right: 8, bottom: 22, left: 36 };
const MAX_BAR = 24;
const GAP = 2;
const RADIUS = 4;

function topRounded(x: number, y: number, w: number, h: number): string {
  const r = Math.min(RADIUS, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

export function StackedBars({
  points,
  series,
  bucketS,
  height = 220,
  unit = "requests",
}: {
  points: SeriesPoint[];
  series: BarSeries[];
  bucketS: number;
  height?: number;
  unit?: string;
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
    // The chart element only exists in chart view: measure it again each time it comes back,
    // otherwise the width falls back to its default after a trip through the table view.
  }, [table]);

  const totals = useMemo(
    () => points.map((p) => series.reduce((sum, s) => sum + Number(p[s.key]), 0)),
    [points, series],
  );
  const max = Math.max(0, ...totals);
  const ticks = niceTicks(max);
  const yMax = ticks[ticks.length - 1] ?? 1;
  const plotW = Math.max(10, width - M.left - M.right);
  const plotH = height - M.top - M.bottom;
  const activeRows = useMemo(
    () => points.filter((p) => series.some((s) => Number(p[s.key]) !== 0)),
    [points, series],
  );
  const hiddenCount = points.length - activeRows.length;
  const slot = plotW / Math.max(1, points.length);
  const barW = Math.max(2, Math.min(MAX_BAR, slot - GAP));
  const y = (v: number) => M.top + plotH - (v / yMax) * plotH;
  const fmt = bucketS >= 86_400 ? dayLabel : bucketS >= 3600 ? dateTime : clock;
  const labelEvery = Math.max(1, Math.ceil(points.length / 5));

  function onMove(e: React.PointerEvent<SVGRectElement>) {
    const box = e.currentTarget.getBoundingClientRect();
    const i = Math.floor(((e.clientX - box.left) / box.width) * points.length);
    setHover(Math.min(points.length - 1, Math.max(0, i)));
  }

  function onKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowRight") setHover((h) => Math.min(points.length - 1, (h ?? -1) + 1));
    else if (e.key === "ArrowLeft") setHover((h) => Math.max(0, (h ?? points.length) - 1));
    else if (e.key === "Escape") setHover(null);
  }

  const hp = hover === null ? null : points[hover];
  const hx = hover === null ? 0 : M.left + hover * slot + slot / 2;
  const flip = hx > width * 0.6;

  return (
    <div>
      <div className="form-row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
        <div className="legend" aria-label="Legend">
          {series.map((s) => (
            <span key={s.label}>
              <span className="swatch" style={{ background: s.color }} />
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
              {activeRows.map((p) => (
                <tr key={p.ts}>
                  <td>{dateTime(p.ts)}</td>
                  {series.map((s) => (
                    <td className="num" key={s.label}>
                      {Number(p[s.key])}
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
            aria-label={`Stacked bar chart of ${unit} over time. Use left and right arrow keys to read values.`}
            onKeyDown={onKey}
            onBlur={() => setHover(null)}
          >
            {ticks.map((t) => (
              <g key={t}>
                <line className={t === 0 ? "axis" : "grid"} x1={M.left} x2={width - M.right} y1={y(t)} y2={y(t)} />
                <text x={M.left - 8} y={y(t) + 4} textAnchor="end">
                  {compact(t)}
                </text>
              </g>
            ))}
            {points.map((p, i) => {
              const cx = M.left + i * slot + slot / 2;
              let acc = 0;
              const segs = series
                .map((s) => ({ s, v: Number(p[s.key]) }))
                .filter((d) => d.v > 0);
              return (
                <g key={p.ts} opacity={hover === null || hover === i ? 1 : 0.55}>
                  {segs.map((d, idx) => {
                    const top = y(acc + d.v);
                    const base = y(acc);
                    const h = Math.max(1, base - top - (idx > 0 ? GAP : 0));
                    const yy = base - (idx > 0 ? GAP : 0) - h;
                    acc += d.v;
                    const isTop = idx === segs.length - 1;
                    return isTop ? (
                      <path key={d.s.label} d={topRounded(cx - barW / 2, yy, barW, h)} fill={d.s.color} />
                    ) : (
                      <rect key={d.s.label} x={cx - barW / 2} y={yy} width={barW} height={h} fill={d.s.color} />
                    );
                  })}
                  {i % labelEvery === 0 && (
                    <text x={cx} y={height - 4} textAnchor="middle">
                      {fmt(p.ts)}
                    </text>
                  )}
                </g>
              );
            })}
            {hover !== null && (
              <line className="axis" x1={hx} x2={hx} y1={M.top} y2={M.top + plotH} strokeDasharray="0" />
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
          {hp && (
            <div
              className="tooltip"
              role="status"
              style={{ top: 8, left: flip ? undefined : hx + 12, right: flip ? width - hx + 12 : undefined }}
            >
              <div className="t-head">{dateTime(hp.ts)}</div>
              {series.map((s) => (
                <div className="t-row" key={s.label}>
                  <span>
                    <span className="key-line" style={{ background: s.color }} />
                    {s.label}
                  </span>
                  <b>{Number(hp[s.key]).toLocaleString()}</b>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
