import { useEffect, useState } from "react";

export type Health = "checking" | "ok" | "down";

/** Polls the gateway's unauthenticated /healthz so the sidebar can show live status. */
export function useGatewayHealth(baseUrl: string, intervalMs = 15_000): Health {
  const [health, setHealth] = useState<Health>("checking");

  useEffect(() => {
    let cancelled = false;
    const url = `${baseUrl.replace(/\/+$/, "")}/healthz`;

    async function probe() {
      try {
        const res = await fetch(url, { cache: "no-store" });
        if (!cancelled) setHealth(res.ok ? "ok" : "down");
      } catch {
        if (!cancelled) setHealth("down");
      }
    }

    setHealth("checking");
    void probe();
    const t = setInterval(() => void probe(), intervalMs);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [baseUrl, intervalMs]);

  return health;
}
