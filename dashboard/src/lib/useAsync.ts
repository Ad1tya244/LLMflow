import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./api";

export interface AsyncState<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
}

/**
 * Runs ``fn`` when ``deps`` change. Previous data is kept while refetching so the
 * layout does not jump; stale responses from superseded calls are discarded.
 */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[], pollMs?: number): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const run = useCallback(() => {
    const id = ++seq.current;
    setLoading(true);
    fnRef
      .current()
      .then((result) => {
        if (id !== seq.current) return;
        setData(result);
        setError(null);
      })
      .catch((e: unknown) => {
        if (id !== seq.current) return;
        setError(e instanceof ApiError ? e : new ApiError(String(e), 0, "unknown"));
      })
      .finally(() => {
        if (id === seq.current) setLoading(false);
      });
  }, []);

  useEffect(() => {
    run();
    if (!pollMs) return;
    const t = setInterval(run, pollMs);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, pollMs]);

  return { data, error, loading, reload: run };
}
