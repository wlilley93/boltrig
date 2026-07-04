import { openRun } from "@/router";
import { TurnExtras } from "@/panels/chatTurnExtras";
import type { NormalizedTurn } from "@/panels/chatTurnTypes";
import { isNotFound } from "./utils";

export function RunEventStream({
  turn,
  resolvedHitls,
  onResolve,
  canReplay,
  replayIdx,
  setReplayIdx,
  eventCount,
  shownCount,
  streamError,
}: {
  turn: NormalizedTurn;
  resolvedHitls: Record<string, string>;
  onResolve: (id: string, status: string) => void;
  canReplay: boolean;
  replayIdx: number | null;
  setReplayIdx: (v: number | null) => void;
  eventCount: number;
  shownCount: number;
  streamError: string | null;
}) {
  return (
    <div className="run-events">
      <div className="kv" style={{ justifyContent: "space-between" }}>
        <h4 style={{ margin: 0 }}>Events</h4>
        {canReplay && (
          <span className="muted" style={{ fontSize: 11 }}>
            {replayIdx === null ? "showing all" : `step ${shownCount} / ${eventCount}`}
          </span>
        )}
      </div>
      {canReplay && (
        <div className="run-replay">
          <input
            type="range"
            min={1}
            max={eventCount}
            value={replayIdx ?? eventCount}
            aria-label="Replay position"
            onChange={(e) => setReplayIdx(Number(e.target.value))}
          />
          <button className="btn btn--sm" onClick={() => setReplayIdx(null)} title="Show the whole run">
            End
          </button>
        </div>
      )}
      <TurnExtras turn={turn} resolvedHitls={resolvedHitls} onResolve={onResolve} onOpenRun={openRun} />
      {turn.text && <div className="chat-msg__text">{turn.text}</div>}
      {eventCount === 0 && !streamError && <p className="muted">No events yet.</p>}
      {streamError && !isNotFound(streamError) && <p className="error">Stream: {streamError}</p>}
    </div>
  );
}
