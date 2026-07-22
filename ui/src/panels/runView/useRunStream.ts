import { useEffect, useMemo, useState } from "react";

import { streamRunEvents } from "@/api/client";
import type { ChatEvent } from "@/api/types";
import { normalizeEvents } from "@/panels/chatTurn";
import { errText } from "@/panels/shared";

export interface RunStream {
  events: ChatEvent[];
  streamError: string | null;
  resolvedHitls: Record<string, string>;
  settled: boolean;
  replayIdx: number | null;
  setReplayIdx: (v: number | null) => void;
  canReplay: boolean;
  shownEvents: ChatEvent[];
  turn: ReturnType<typeof normalizeEvents>;
  resolveHitl: (id: string, status: string) => void;
}

// Follow the run's event stream live; the same SSE vocabulary Chat renders.
// replay: once the run has settled, the scrubber reveals events up to an index
// (null = show everything / follow live).
export function useRunStream(runId: string): RunStream {
  const [events, setEvents] = useState<ChatEvent[]>([]);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [resolvedHitls, setResolvedHitls] = useState<Record<string, string>>({});
  const [settled, setSettled] = useState(false);
  const [replayIdx, setReplayIdx] = useState<number | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    let terminalTimer: number | undefined;
    setEvents([]);
    setStreamError(null);
    setResolvedHitls({});
    setSettled(false);
    setReplayIdx(null);
    streamRunEvents(
      runId,
      (ev) => {
        setEvents((prev) => [...prev, ev]);
        if (ev.type === "workflow_run" && ev.status !== "paused") {
          setSettled(true);
          terminalTimer = window.setTimeout(() => ctrl.abort(), 50);
        }
      },
      { signal: ctrl.signal, follow: true },
    )
      .then(() => {
        if (!ctrl.signal.aborted) setSettled(true);
      })
      .catch((err) => {
        if (!ctrl.signal.aborted) setStreamError(errText(err));
      });
    return () => {
      if (terminalTimer !== undefined) window.clearTimeout(terminalTimer);
      ctrl.abort();
    };
  }, [runId]);

  const canReplay = settled && events.length > 1;
  const shownEvents =
    replayIdx !== null ? events.slice(0, Math.max(0, Math.min(replayIdx, events.length))) : events;
  const turn = useMemo(() => normalizeEvents(shownEvents), [shownEvents]);

  function resolveHitl(id: string, status: string) {
    setResolvedHitls((prev) => ({ ...prev, [id]: status }));
  }

  return {
    events, streamError, resolvedHitls, settled, replayIdx, setReplayIdx,
    canReplay, shownEvents, turn, resolveHitl,
  };
}
