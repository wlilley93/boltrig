// Minimal data-fetching hook: loading / error / data plus a manual reload and
// optional polling. Keeps the panels thin without pulling in a data library.

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "./api/client";

export interface FetchState<T> {
  data: T | null;
  error: string | null;
  // the HTTP status when the failure was an ApiError (403 = denied, 0 = network,
  // 5xx = server bug); null otherwise. Lets a panel render a calm "denied" or
  // "can't reach the server" instead of a red bug, and offer a retry.
  errorStatus: number | null;
  loading: boolean;
  reload: () => void;
}

function describe(err: unknown): { message: string; status: number | null } {
  if (err instanceof ApiError) {
    if (err.status === 403) return { message: "You don't have access to this.", status: 403 };
    if (err.status === 0)
      return { message: "Can't reach the server - check your connection.", status: 0 };
    const detail =
      err.body && typeof err.body === "object" && "reason" in err.body
        ? `: ${String((err.body as { reason: unknown }).reason)}`
        : "";
    return { message: `Something went wrong${detail}`, status: err.status };
  }
  return { message: err instanceof Error ? err.message : String(err), status: null };
}

export function useFetch<T>(
  fn: () => Promise<T>,
  deps: ReadonlyArray<unknown> = [],
  pollMs?: number,
): FetchState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const active = useRef(true);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(fn, deps);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await run();
      if (active.current) {
        setData(result);
        setError(null);
        setErrorStatus(null);
      }
    } catch (err) {
      if (active.current) {
        const d = describe(err);
        setError(d.message);
        setErrorStatus(d.status);
      }
    } finally {
      if (active.current) setLoading(false);
    }
  }, [run]);

  useEffect(() => {
    active.current = true;
    void load();
    return () => {
      active.current = false;
    };
  }, [load]);

  useEffect(() => {
    if (!pollMs) return;
    const handle = window.setInterval(() => void load(), pollMs);
    return () => window.clearInterval(handle);
  }, [load, pollMs]);

  return { data, error, errorStatus, loading, reload: () => void load() };
}
