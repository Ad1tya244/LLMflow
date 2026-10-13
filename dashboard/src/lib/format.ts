export function compact(n: number): string {
  if (Math.abs(n) < 1000) return String(Math.round(n));
  return new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

export function usd(n: number | null | undefined): string {
  if (n === null || n === undefined) return "–";
  if (n === 0) return "$0.00";
  if (Math.abs(n) >= 1) return `$${n.toFixed(2)}`;
  if (Math.abs(n) >= 0.01) return `$${n.toFixed(3)}`;
  return `$${n.toFixed(5)}`;
}

export function ms(n: number | null | undefined): string {
  if (n === null || n === undefined) return "–";
  return n >= 1000 ? `${(n / 1000).toFixed(1)} s` : `${Math.round(n)} ms`;
}

export function pct(fraction: number): string {
  const v = fraction * 100;
  return `${v < 10 && v > 0 ? v.toFixed(1) : Math.round(v)}%`;
}

export function clock(tsSeconds: number): string {
  return new Date(tsSeconds * 1000).toLocaleTimeString("en", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function dateTime(tsSeconds: number): string {
  return new Date(tsSeconds * 1000).toLocaleString("en", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/** Round-number axis ticks from 0 to just above ``max``. */
export function niceTicks(max: number, target = 4): number[] {
  if (max <= 0) return [0, 1];
  const raw = max / target;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
  const ticks: number[] = [];
  for (let v = 0; v < max + step; v += step) ticks.push(Math.round(v * 1e9) / 1e9);
  return ticks;
}

/** USD per 1M tokens with a stable number of decimals so columns line up (0.075, 0.15, 0.60). */
export function pricePerM(n: number): string {
  return n < 0.1 && n > 0 ? n.toFixed(3) : n.toFixed(2);
}
