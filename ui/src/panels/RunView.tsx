// The global Run inspector. Keyed by a run_id and reachable from every surface
// that shows one, it keeps the audit summary, live timeline, execution tree and
// raw audit record in one stable drawer. Tool-call and approval tabs appear only
// after those event types have actually been observed.
// Authz stays server-side: a 404 from auditTree / streamRunEvents renders as a
// clean "run not found / not in scope" state, never a pre-check.

import { useEffect, useRef } from "react";

import { api } from "../api/client";
import { closeRun, navigate, useRoute } from "../router";
import { useFetch } from "../useFetch";
import { useFocusTrap } from "../useFocusTrap";
import { RunInspector } from "./runView/RunInspector";
import { useRunStream } from "./runView/useRunStream";
import { isNotFound } from "./runView/utils";

export function RunDrawer({ runId }: { runId: string }) {
  const tree = useFetch(() => api.auditTree(runId), [runId]);
  const stream = useRunStream(runId);

  // Both the tree fetch and the stream 404 when the run is unknown / out of
  // scope; show one clean message rather than two raw errors.
  const treeNotFound = tree.errorStatus === 404 || isNotFound(tree.error);
  const notFound = treeNotFound && isNotFound(stream.streamError);

  // a11y: Esc closes the drawer; focus is trapped inside it while open and
  // restored to the opener on close (useFocusTrap).
  const drawerRef = useRef<HTMLDivElement>(null);
  useFocusTrap(drawerRef);
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (
        e.key === "Escape" &&
        !e.defaultPrevented &&
        document.querySelector(".cmdk-overlay") === null
      ) {
        e.preventDefault();
        closeRun();
      }
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
      <div
        className="drawer run-inspector-drawer"
        ref={drawerRef}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="drawer__head run-inspector-drawer__head">
          <h3>Run</h3>
          <div className="kv">
            <button type="button" className="btn btn--ghost" onClick={() => navigate("/runs")}>
              All runs
            </button>
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => navigate("/insight")}
            >
              Audit &amp; costs
            </button>
            <button
              type="button"
              className="btn btn--ghost"
              aria-label="Close run inspector"
              onClick={() => closeRun()}
            >
              close
            </button>
          </div>
        </div>
        <p className="muted run-inspector-drawer__run-id">
          run <code>{runId}</code>
        </p>

        {notFound ? (
          <p className="notice warn run-inspector__not-found">
            Run not found, or not in your visibility scope.
          </p>
        ) : (
          <RunInspector
            tree={{ data: tree.data, loading: tree.loading, error: tree.error }}
            stream={stream}
          />
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
