// Minimal data-fetching hook: loading / error / data plus a manual reload and
// optional polling. Keeps the panels thin without pulling in a data library.

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "./api/client";

export interface FetchState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

function describe(err: unknown): string {
  if (err instanceof ApiError) {
    const detail =
      err.body && typeof err.body === "object" && "reason" in err.body
        ? ` (${String((err.body as { reason: unknown }).reason)})`
        : "";
    return `${err.message}${detail}`;
  }
  return err instanceof Error ? err.message : String(err);
}

export function useFetch<T>(
  fn: () => Promise<T>,
  deps: ReadonlyArray<unknown> = [],
  pollMs?: number,
): FetchState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
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
      }
    } catch (err) {
      if (active.current) setError(describe(err));
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

  return { data, error, loading, reload: () => void load() };
}
