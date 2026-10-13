import { useEffect, useState } from "react";

export type RouteId =
  | "overview"
  | "requests"
  | "providers"
  | "keys"
  | "connect"
  | "playground"
  | "benchmarks"
  | "settings";
const ROUTES: RouteId[] = [
  "overview",
  "requests",
  "providers",
  "keys",
  "connect",
  "playground",
  "benchmarks",
  "settings",
];

function parse(): RouteId {
  const id = window.location.hash.replace(/^#\/?/, "") as RouteId;
  return ROUTES.includes(id) ? id : "overview";
}

export function useRoute(): RouteId {
  const [route, setRoute] = useState<RouteId>(parse);
  useEffect(() => {
    const on = () => setRoute(parse());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}
