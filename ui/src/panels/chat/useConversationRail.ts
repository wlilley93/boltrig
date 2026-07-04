import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, api } from "@/api/client";
import type { ConversationSearchResult } from "@/api/types";
import { apiReason } from "@/panels/shared";
import { PAGE_SIZE, SEARCH_DEBOUNCE_MS } from "@/panels/chat/constants";
import type { RailMode, RailState } from "@/panels/chat/types";

function errStatus(err: unknown): number | null {
  return err instanceof ApiError ? err.status : null;
}

async function fetchPage(
  q: string,
  offset: number,
): Promise<{ items: ConversationSearchResult[]; nextOffset: number | null }> {
  if (q) {
    const res = await api.searchConversations(q, PAGE_SIZE, offset);
    return { items: res.results, nextOffset: res.next_offset ?? null };
  }
  const res = await api.listConversations(PAGE_SIZE, offset);
  return { items: res.conversations.map((c) => ({ ...c, snippet: null })), nextOffset: res.next_offset ?? null };
}

async function fetchFirstPage(
  q: string,
  seq: React.MutableRefObject<number>,
  alive: React.MutableRefObject<boolean>,
  setState: React.Dispatch<React.SetStateAction<RailState>>,
  background: boolean,
): Promise<void> {
  const mine = ++seq.current;
  const mode: RailMode = q ? "search" : "list";
  if (!background) {
    setState((s) => ({
      ...s,
      loading: true,
      loadingMore: false,
      error: null,
      errorStatus: null,
    }));
  }
  try {
    const { items, nextOffset } = await fetchPage(q, 0);
    if (!alive.current || mine !== seq.current) return;
    setState({
      mode,
      items,
      nextOffset,
      loading: false,
      loadingMore: false,
      error: null,
      errorStatus: null,
    });
  } catch (err) {
    if (!alive.current || mine !== seq.current) return;
    setState((s) => ({
      ...s,
      loading: false,
      loadingMore: false,
      error: apiReason(err),
      errorStatus: errStatus(err),
    }));
  }
}

async function fetchNextPage(
  stateRef: React.MutableRefObject<RailState>,
  seq: React.MutableRefObject<number>,
  alive: React.MutableRefObject<boolean>,
  q: string,
  setState: React.Dispatch<React.SetStateAction<RailState>>,
): Promise<void> {
  const cur = stateRef.current;
  if (cur.nextOffset === null || cur.loading || cur.loadingMore) return;
  const offset = cur.nextOffset;
  const mine = seq.current;
  setState((s) => ({ ...s, loadingMore: true }));
  try {
    const { items: more, nextOffset } = await fetchPage(q, offset);
    if (!alive.current || mine !== seq.current) return;
    setState((s) => {
      const seen = new Set(s.items.map((i) => i.id));
      return {
        ...s,
        items: [...s.items, ...more.filter((m) => !seen.has(m.id))],
        nextOffset,
        loadingMore: false,
      };
    });
  } catch (err) {
    if (!alive.current || mine !== seq.current) return;
    setState((s) => ({
      ...s,
      loadingMore: false,
      error: apiReason(err),
      errorStatus: errStatus(err),
    }));
  }
}

// The conversation rail's data engine: it owns the paginated list, the debounced
// search, and the next_offset cursor, and exposes reload() (refetch the first
// page in place, e.g. after a send / delete / rename) and loadMore() (append the
// next page). A monotonic request id drops stale in-flight responses so a fast
// switch between the list and a search term never renders the wrong page.
export function useConversationRail(query: string) {
  const trimmed = query.trim();
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const delay = trimmed ? SEARCH_DEBOUNCE_MS : 0;
    const timer = window.setTimeout(() => setDebounced(trimmed), delay);
    return () => window.clearTimeout(timer);
  }, [trimmed]);

  const [state, setState] = useState<RailState>({
    mode: "list",
    items: [],
    nextOffset: null,
    loading: true,
    loadingMore: false,
    error: null,
    errorStatus: null,
  });
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const seq = useRef(0);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const fetchFirst = useCallback(
    async (background: boolean) => fetchFirstPage(debounced, seq, alive, setState, background),
    [debounced],
  );

  useEffect(() => {
    void fetchFirst(false);
  }, [fetchFirst]);

  const loadMore = useCallback(
    async () => fetchNextPage(stateRef, seq, alive, debounced, setState),
    [debounced],
  );

  return { state, reload: () => void fetchFirst(true), loadMore };
}

export type { RailState } from "@/panels/chat/types";
