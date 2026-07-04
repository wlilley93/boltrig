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
//
// RunDrawer is now a thin orchestrator: the live event stream (with replay)
// lives in useRunStream, and the summary, event stream and execution tree each
// render through their own sub-component in runView/.

import { useEffect, useRef } from "react";

import { api } from "../api/client";
import { closeRun, useRoute } from "../router";
import { useFetch } from "../useFetch";
import { useFocusTrap } from "../useFocusTrap";
import { RunSummary } from "./runView/RunSummary";
import { RunEventStream } from "./runView/RunEventStream";
import { RunExecutionTree } from "./runView/RunExecutionTree";
import { useRunStream } from "./runView/useRunStream";
import { isNotFound } from "./runView/utils";

function RunDrawer({ runId }: { runId: string }) {
  const tree = useFetch(() => api.auditTree(runId), [runId]);
  const stream = useRunStream(runId);

  const root = tree.data?.root;
  const statuses = root?.statuses
    ? Object.entries(root.statuses).map(([s, n]) => `${s}:${n}`).join(" ")
    : "";

  // Both the tree fetch and the stream 404 when the run is unknown / out of
  // scope; show one clean message rather than two raw errors.
  const notFound = isNotFound(tree.error) && isNotFound(stream.streamError);

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
          <p className="notice warn">Run not found, or not in your visibility scope.</p>
        ) : (
          <>
            <RunSummary root={root} statuses={statuses} />
            <RunEventStream
              turn={stream.turn}
              resolvedHitls={stream.resolvedHitls}
              onResolve={stream.resolveHitl}
              canReplay={stream.canReplay}
              replayIdx={stream.replayIdx}
              setReplayIdx={stream.setReplayIdx}
              eventCount={stream.events.length}
              shownCount={stream.shownEvents.length}
              streamError={stream.streamError}
            />
            <RunExecutionTree loading={tree.loading && !tree.data} error={tree.error} root={root} />
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
