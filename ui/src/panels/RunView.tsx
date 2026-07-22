// The global Run inspector. Keyed by a run_id and reachable from every surface
// that shows one, it keeps the audit summary, live timeline, execution tree and
// raw audit record in one stable drawer. Tool-call and approval tabs appear only
// after those event types have actually been observed.
// Authz stays server-side: a 404 from auditTree / streamRunEvents renders as a
// clean "run not found / not in scope" state, never a pre-check.

import { useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import { closeRun, navigate, openRun, useRoute } from "../router";
import { useFetch } from "../useFetch";
import { useFocusTrap } from "../useFocusTrap";
import { RunInspector } from "./runView/RunInspector";
import { useRunStream } from "./runView/useRunStream";
import { isNotFound } from "./runView/utils";

function runCrumbLabel(runId: string): string {
  return runId.length > 18 ? `${runId.slice(0, 8)}...${runId.slice(-6)}` : runId;
}

export function nextRunTrail(
  current: string[],
  runId: string | undefined,
): string[] {
  if (!runId) return [];
  if (current[current.length - 1] === runId) return current;
  const existing = current.indexOf(runId);
  if (existing >= 0) return current.slice(0, existing + 1);
  return [...current, runId];
}

export function RunDrawer({
  runId,
  trail = [runId],
  onSelectRun = openRun,
}: {
  runId: string;
  trail?: string[];
  onSelectRun?: (runId: string) => void;
}) {
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
        <nav className="run-trail" aria-label="Run ancestry">
          {trail.map((trailRunId, index) => {
            const current = index === trail.length - 1;
            return (
              <span className="run-trail__item" key={`${trailRunId}-${index}`}>
                {index > 0 && <span aria-hidden="true">/</span>}
                {current ? (
                  <code aria-current="page" title={trailRunId}>
                    {runCrumbLabel(trailRunId)}
                  </code>
                ) : (
                  <button
                    type="button"
                    className="run-trail__link"
                    title={`Return to run ${trailRunId}`}
                    onClick={() => onSelectRun(trailRunId)}
                  >
                    {runCrumbLabel(trailRunId)}
                  </button>
                )}
              </span>
            );
          })}
        </nav>

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
  const [trail, setTrail] = useState<string[]>(() =>
    route.runId ? [route.runId] : [],
  );

  useEffect(() => {
    setTrail((current) => nextRunTrail(current, route.runId));
  }, [route.runId]);

  if (!route.runId) return null;
  const visibleTrail = nextRunTrail(trail, route.runId);
  return (
    <RunDrawer
      runId={route.runId}
      trail={visibleTrail}
      onSelectRun={openRun}
      key={route.runId}
    />
  );
}
