import { useEffect, useRef, useState } from "react";
import { niceTicks, usd } from "../lib/format";
import type { StrategyResult } from "../lib/types";

const M = { top: 12, right: 24, bottom: 36, left: 48 };

/** Accuracy (with 95% interval) against shadow cost, one point per strategy. */
export function CostAccuracy({ strategies }: { strategies: Record<string, StrategyResult> }) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(640);
  const [hover, setHover] = useState<string | null>(null);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    setWidth(el.clientWidth || 640);
    const ro = new ResizeObserver(() => setWidth(el.clientWidth || 640));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const names = Object.keys(strategies);
  const height = 260;
  const maxCost = Math.max(1e-9, ...names.map((n) => strategies[n]?.shadow_cost_usd ?? 0));
  const xTicks = niceTicks(maxCost * 1.1, 4);
  const xMax = xTicks[xTicks.length - 1] ?? 1;
  const plotW = Math.max(10, width - M.left - M.right);
  const plotH = height - M.top - M.bottom;
  const x = (v: number) => M.left + (v / xMax) * plotW;
  const y = (a: number) => M.top + plotH - a * plotH;
  const routed = (n: string) => n.startsWith("routed");

  // Points often coincide (several strategies at 100%). Place each label at the first
  // vertical offset that does not collide with an already-placed label.
  const LABEL_H = 14;
  const placed: { x0: number; x1: number; y: number }[] = [];
  const labelY = new Map<string, number>();
  [...names]
    .sort((a, b) => (strategies[a]?.shadow_cost_usd ?? 0) - (strategies[b]?.shadow_cost_usd ?? 0))
    .forEach((n) => {
      const sres = strategies[n];
      if (!sres) return;
      const x0 = x(sres.shadow_cost_usd) + 10;
      const x1 = x0 + n.length * 6.6;
      const base = y(sres.accuracy);
      for (const off of [-10, 8, -24, 22, -38, 36, -52, 50]) {
        const yy = base + off;
        const clash = placed.some((r) => r.x0 < x1 && x0 < r.x1 && Math.abs(r.y - yy) < LABEL_H);
        if (!clash) {
          placed.push({ x0, x1, y: yy });
          labelY.set(n, yy);
          return;
        }
      }
      labelY.set(n, base - 10);
    });

  return (
    <div className="chart" ref={wrap}>
      <svg width={width} height={height} role="img" aria-label="Accuracy versus shadow cost per strategy">
        {[0, 0.25, 0.5, 0.75, 1].map((t) => (
          <g key={t}>
            <line className={t === 0 ? "axis" : "grid"} x1={M.left} x2={width - M.right} y1={y(t)} y2={y(t)} />
            <text x={M.left - 8} y={y(t) + 4} textAnchor="end">
              {Math.round(t * 100)}%
            </text>
          </g>
        ))}
        {xTicks.map((t) => (
          <text key={t} x={x(t)} y={height - 14} textAnchor="middle">
            {usd(t)}
          </text>
        ))}
        {names.map((n) => {
          const s = strategies[n];
          if (!s) return null;
          const cx = x(s.shadow_cost_usd);
          const color = routed(n) ? "var(--accent)" : "var(--text-3)";
          return (
            <g key={n} onPointerEnter={() => setHover(n)} onPointerLeave={() => setHover(null)}>
              <line x1={cx} x2={cx} y1={y(s.accuracy_ci95[0])} y2={y(s.accuracy_ci95[1])} stroke={color} strokeWidth={2} opacity={0.5} />
              <circle cx={cx} cy={y(s.accuracy)} r={routed(n) ? 6 : 5} fill={color} stroke="var(--surface)" strokeWidth={2} />
              <circle cx={cx} cy={y(s.accuracy)} r={16} fill="transparent" />
              <text x={cx + 10} y={labelY.get(n) ?? y(s.accuracy) - 8} style={{ fill: "var(--text)" }}>
                {n}
              </text>
            </g>
          );
        })}
      </svg>
      {hover && strategies[hover] && (
        <div className="tooltip" role="status" style={{ top: 8, right: 8 }}>
          <div className="t-head">{hover}</div>
          <div className="t-row">
            <span>Accuracy</span>
            <b>{(strategies[hover].accuracy * 100).toFixed(0)}%</b>
          </div>
          <div className="t-row">
            <span>Shadow cost</span>
            <b>{usd(strategies[hover].shadow_cost_usd)}</b>
          </div>
        </div>
      )}
      <div className="legend" style={{ marginTop: 8 }}>
        <span>
          <span className="swatch" style={{ background: "var(--text-3)" }} />
          Fixed model
        </span>
        <span>
          <span className="swatch" style={{ background: "var(--accent)" }} />
          Routed
        </span>
        <span className="muted">Vertical bar: 95% interval</span>
      </div>
    </div>
  );
}
