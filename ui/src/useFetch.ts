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
  // paused pauses ONLY the poll interval (the initial fetch still runs); a
  // paused -> active edge triggers one immediate load so a deck slide that
  // quiesced while parked is fresh the moment it is revealed.
  opts?: { paused?: boolean },
): FetchState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const active = useRef(true);
  const hasData = useRef(false); // mirrors data!=null without re-capturing the closure
  const seq = useRef(0); // monotonic request id: drop stale in-flight responses
  const paused = opts?.paused ?? false;

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(fn, deps);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    // Only show the blocking "loading" state on the first load; a poll/reload
    // that already has data refreshes in place (no spinner flash, no button
    // flicker). Panels keep using `loading && !data` for the initial spinner.
    if (!hasData.current) setLoading(true);
    try {
      const result = await run();
      // A newer load() superseded this one (fast poll, changed deps) - its
      // response is the source of truth; drop this stale one.
      if (active.current && mine === seq.current) {
        setData(result);
        hasData.current = true;
        setError(null);
        setErrorStatus(null);
      }
    } catch (err) {
      if (active.current && mine === seq.current) {
        const d = describe(err);
        setError(d.message);
        setErrorStatus(d.status);
      }
    } finally {
      if (active.current && mine === seq.current) setLoading(false);
    }
  }, [run]);

  useEffect(() => {
    active.current = true;
    // `load` identity changes only when deps change (or first mount): the data we
    // hold is for the previous query, so re-show the initial loading state.
    hasData.current = false;
    void load();
    return () => {
      active.current = false;
    };
  }, [load]);

  useEffect(() => {
    if (!pollMs || paused) return;
    const handle = window.setInterval(() => void load(), pollMs);
    return () => window.clearInterval(handle);
  }, [load, pollMs, paused]);

  // one immediate refresh on the paused -> active edge (not on mount: the
  // initial-load effect above already covers that).
  const wasPaused = useRef(false);
  useEffect(() => {
    if (wasPaused.current && !paused) void load();
    wasPaused.current = paused;
  }, [paused, load]);

  return { data, error, errorStatus, loading, reload: () => void load() };
}
