import { useEffect, useState } from "react";

/** Signed-out screens. Anything that is not an explicit auth route shows the landing page. */
export type AuthRoute = "landing" | "signin" | "signup" | "recover";

export function parseAuthRoute(hash: string): AuthRoute {
  const id = hash.replace(/^#\/?/, "");
  if (id === "signin" || id === "signup" || id === "recover") return id;
  return "landing";
}

export function useAuthRoute(): AuthRoute {
  const [route, setRoute] = useState<AuthRoute>(() => parseAuthRoute(window.location.hash));
  useEffect(() => {
    const on = () => setRoute(parseAuthRoute(window.location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}
