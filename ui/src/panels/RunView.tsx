// The global Run drawer (Round Eleven front-end item 2). Keyed by a run_id and
// reachable from every surface that shows one (Kanban cards, Insight runs and
// audit rows, Approvals context, workflow run records), it absorbs the bespoke
// Kanban audit drawer into a single place. It shows three things for the run:
//   - a cost / status summary from the audit-tree root,
//   - the live (follow) event stream rendered with the shared chat renderer, so
//     tool calls, reasoning, sub-agents and inline HITL look identical to Chat;
//     a sub-agent card links to its child run, navigating the drawer down the
//     run nesting the backbone enables,
//   - the full execution tree (recursive AuditNodeView).
// Authz stays server-side: a 404 from auditTree / streamRunEvents renders as a
// clean "run not found / not in scope" state, never a pre-check.

import { useEffect, useMemo, useRef, useState } from "react";

import { api, streamRunEvents } from "../api/client";
import type { AuditNode, ChatEvent } from "../api/types";
import { closeRun, openRun, useRoute } from "../router";
import { useFetch } from "../useFetch";
import { useFocusTrap } from "../useFocusTrap";
import { TurnExtras, normalizeEvents } from "./chatTurn";
import { errText } from "./shared";

// Recursive audit-tree node (ported from the old Kanban drawer so the tree
// renders the same everywhere).
function AuditNodeView({ node }: { node: AuditNode }) {
  const statuses = node.statuses
    ? Object.entries(node.statuses)
        .map(([s, n]) => `${s}:${n}`)
        .join(" ")
    : "";
  return (
    <li className="audit-node">
      <div className="audit-node__line">
        <code>{node.run_id}</code>
        {node.actor ? <span className="muted"> {node.actor}</span> : null}
        {node.tier ? <span className="badge">{node.tier}</span> : null}
        {statuses ? <span className="muted"> [{statuses}]</span> : null}
        {typeof node.total_cost_micros === "number" ? (
          <span className="muted"> cost: {node.total_cost_micros}µ</span>
        ) : null}
      </div>
      {node.children && node.children.length > 0 ? (
        <ul className="audit-tree">
          {node.children.map((c) => (
            <AuditNodeView node={c} key={c.run_id} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function isNotFound(err: string | null): boolean {
  return !!err && (err.includes("404") || err.toLowerCase().includes("not found"));
}

function RunDrawer({ runId }: { runId: string }) {
  const tree = useFetch(() => api.auditTree(runId), [runId]);

  const [events, setEvents] = useState<ChatEvent[]>([]);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [resolvedHitls, setResolvedHitls] = useState<Record<string, string>>({});
  // replay: once the run has settled, the scrubber reveals events up to an index
  // (null = show everything / follow live).
  const [settled, setSettled] = useState(false);
  const [replayIdx, setReplayIdx] = useState<number | null>(null);

  // Follow the run's event stream live; the same SSE vocabulary Chat renders.
  useEffect(() => {
    const ctrl = new AbortController();
    setEvents([]);
    setStreamError(null);
    setResolvedHitls({});
    setSettled(false);
    setReplayIdx(null);
    streamRunEvents(
      runId,
      (ev) => setEvents((prev) => [...prev, ev]),
      { signal: ctrl.signal, follow: true },
    )
      .then(() => {
        if (!ctrl.signal.aborted) setSettled(true);
      })
      .catch((err) => {
        if (!ctrl.signal.aborted) setStreamError(errText(err));
      });
    return () => ctrl.abort();
  }, [runId]);

  const canReplay = settled && events.length > 1;
  const shownEvents =
    replayIdx !== null ? events.slice(0, Math.max(0, Math.min(replayIdx, events.length))) : events;
  const turn = useMemo(() => normalizeEvents(shownEvents), [shownEvents]);
  const root = tree.data?.root;
  const statuses = root?.statuses
    ? Object.entries(root.statuses)
        .map(([s, n]) => `${s}:${n}`)
        .join(" ")
    : "";

  // Both the tree fetch and the stream 404 when the run is unknown / out of
  // scope; show one clean message rather than two raw errors.
  const notFound = isNotFound(tree.error) && isNotFound(streamError);

  function resolveHitl(id: string, status: string) {
    setResolvedHitls((prev) => ({ ...prev, [id]: status }));
  }

  // a11y: Esc closes the drawer; focus is trapped inside it while open and
  // restored to the opener on close (useFocusTrap).
  const drawerRef = useRef<HTMLDivElement>(null);
  useFocusTrap(drawerRef);
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") closeRun();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div
      className="drawer-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="Run details"
      onClick={() => closeRun()}
    >
      <div className="drawer" ref={drawerRef} tabIndex={-1} onClick={(e) => e.stopPropagation()}>
        <div className="drawer__head">
          <h3>Run</h3>
          <button className="btn btn--ghost" onClick={() => closeRun()}>
            close
          </button>
        </div>
        <p className="muted">
          run <code>{runId}</code>
        </p>

        {notFound ? (
          <p className="notice warn">
            Run not found, or not in your visibility scope.
          </p>
        ) : (
          <>
            {/* Cost / status summary from the tree root. */}
            {root && (
              <div className="kv">
                {root.actor ? <span className="muted">{root.actor}</span> : null}
                {root.tier ? <span className="badge">{root.tier}</span> : null}
                {statuses ? <span className="muted">[{statuses}]</span> : null}
                {typeof root.total_cost_micros === "number" ? (
                  <span className="muted">cost: {root.total_cost_micros}µ</span>
                ) : null}
              </div>
            )}

            {/* Live / snapshot event stream, rendered with the chat renderer. */}
            <div className="run-events">
              <div className="kv" style={{ justifyContent: "space-between" }}>
                <h4 style={{ margin: 0 }}>Events</h4>
                {canReplay && (
                  <span className="muted" style={{ fontSize: 11 }}>
                    {replayIdx === null ? "showing all" : `step ${shownEvents.length} / ${events.length}`}
                  </span>
                )}
              </div>
              {canReplay && (
                <div className="run-replay">
                  <input
                    type="range"
                    min={1}
                    max={events.length}
                    value={replayIdx ?? events.length}
                    aria-label="Replay position"
                    onChange={(e) => setReplayIdx(Number(e.target.value))}
                  />
                  <button
                    className="btn btn--sm"
                    onClick={() => setReplayIdx(null)}
                    title="Show the whole run"
                  >
                    End
                  </button>
                </div>
              )}
              <TurnExtras
                turn={turn}
                resolvedHitls={resolvedHitls}
                onResolve={resolveHitl}
                onOpenRun={openRun}
              />
              {turn.text && <div className="chat-msg__text">{turn.text}</div>}
              {events.length === 0 && !streamError && (
                <p className="muted">No events yet.</p>
              )}
              {streamError && !isNotFound(streamError) && (
                <p className="error">Stream: {streamError}</p>
              )}
            </div>

            {/* Full execution tree. */}
            <div className="run-tree">
              <h4>Execution tree</h4>
              {tree.loading && !tree.data && <p className="muted">Loading...</p>}
              {tree.error && !isNotFound(tree.error) && (
                <p className="error">{tree.error}</p>
              )}
              {root && (
                <ul className="audit-tree audit-tree--root">
                  <AuditNodeView node={root} />
                </ul>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// Mounted once, globally: it watches the route and raises the drawer whenever a
// run id is present. key={runId} resets the stream when navigating to a child.
export function RunView() {
  const route = useRoute();
  if (!route.runId) return null;
  return <RunDrawer runId={route.runId} key={route.runId} />;
}
