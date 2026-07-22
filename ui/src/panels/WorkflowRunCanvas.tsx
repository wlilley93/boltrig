// Live run view of the workflow canvas (front-end item 3): the SAME node graph
// the author built, lighting up as the interpreter executes it. It is the
// complement of the Run drawer (RunView) - the drawer is the event log + tree;
// this is the graph itself colouring by execution state.
//
// It reuses WorkflowCanvas's graph helpers verbatim (stepsToGraph / extractSteps
// / nodeTypes), so the static graph is byte-for-byte the authoring layout. On
// top of that static graph it overlays per-node run state read from the run's
// live event stream: each `workflow_step` event names a step_id, which we match
// to a node id (node.id === step_id) and recolour. follow:true replays whatever
// already happened, then keeps updating live, so this works for an in-flight run
// and for one that already finished. Authz stays server-side: a 404 from
// getWorkflow / streamRunEvents renders as a clean "not found" state.

import { useEffect, useMemo, useState } from "react";

import { ReactFlow, Background, Controls, MiniMap } from "@xyflow/react";

import "@xyflow/react/dist/style.css";

import { api, streamRunEvents } from "../api/client";
import type { ChatEvent, VerbInfo } from "../api/types";
import { openRun } from "../router";
import { useFetch } from "../useFetch";
import {
  extractSteps,
  nodeTypes,
  stepsToGraph,
  type RunNodeStatus,
} from "./WorkflowCanvas";
import { errText } from "./shared";
import { overlayRunState } from "./workflowCanvas/runState";
import { edgeTypes } from "./workflowCanvas/edges";

function isNotFound(err: string | null): boolean {
  return !!err && (err.includes("404") || err.toLowerCase().includes("not found"));
}

function isTerminalWorkflowEvent(event: ChatEvent): boolean {
  return event.type === "workflow_run" && event.status !== "paused";
}

async function followRunWithStartupRetry(
  runId: string,
  onEvent: (event: ChatEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  for (let attempt = 0; ; attempt += 1) {
    try {
      await streamRunEvents(runId, onEvent, { signal, follow: true });
      return;
    } catch (error) {
      if (signal.aborted) throw error;
      if (attempt >= 8 || !isNotFound(errText(error))) throw error;
      await new Promise((resolve) => window.setTimeout(resolve, 150));
    }
  }
}

interface WorkflowRunCanvasProps {
  runId: string;
  // The workflow whose stored steps form the static graph (Run knows it; an
  // existing-run viewer passes the workflow id alongside the run id).
  wfId: string;
  // Optional control to return to the authoring canvas.
  onBack?: () => void;
}

export function WorkflowRunCanvas({ runId, wfId, onBack }: WorkflowRunCanvasProps) {
  const caps = useFetch(() => api.capabilities(), []);
  const detail = useFetch(() => api.getWorkflow(wfId), [wfId]);

  // Per-step status keyed by step_id (=== node id), updated from workflow_step
  // events; streamDone stops the running pulse once the stream closes.
  const [statusById, setStatusById] = useState<Record<string, RunNodeStatus>>({});
  const [streamDone, setStreamDone] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);

  const verbsById = useMemo(() => {
    const verbs: VerbInfo[] = caps.data?.verbs ?? [];
    return new Map(verbs.map((v) => [v.id, v]));
  }, [caps.data]);

  // The static graph (authoring layout), rebuilt only when the definition or the
  // verb bindings change - not on every status tick.
  const base = useMemo(() => {
    const steps = extractSteps(detail.data?.definition) ?? [];
    return stepsToGraph(steps, verbsById);
  }, [detail.data, verbsById]);

  // Follow the run's stream: replay-then-live. Each workflow_step lights a node.
  useEffect(() => {
    const ctrl = new AbortController();
    let terminalTimer: number | undefined;
    setStatusById({});
    setStreamDone(false);
    setStreamError(null);
    followRunWithStartupRetry(
      runId,
      (ev: ChatEvent) => {
        if (ev.type === "workflow_step") {
          setStatusById((prev) => ({ ...prev, [ev.step_id]: ev.status }));
        }
        if (isTerminalWorkflowEvent(ev)) {
          setStreamDone(true);
          // Let any event already buffered behind the terminal marker render,
          // then release the long-lived follow socket.
          terminalTimer = window.setTimeout(() => ctrl.abort(), 50);
        }
      },
      ctrl.signal,
    )
      .then(() => {
        if (!ctrl.signal.aborted) setStreamDone(true);
      })
      .catch((err) => {
        if (!ctrl.signal.aborted) setStreamError(errText(err));
      });
    return () => {
      if (terminalTimer !== undefined) window.clearTimeout(terminalTimer);
      ctrl.abort();
    };
  }, [runId]);

  // Overlay status onto the same authored graph. Nodes carry a glyph + ring;
  // each incoming edge carries the target step's live or settled state.
  const { nodes, edges } = useMemo(
    () => overlayRunState(base.nodes, base.edges, statusById, streamDone),
    [base.nodes, base.edges, statusById, streamDone],
  );

  const notFound = isNotFound(detail.error) && isNotFound(streamError);

  return (
    <div className="stack">
      <div className="form">
        <div className="form__title">Live run</div>
        <div className="kv">
          <span className="muted">
            run <code>{runId}</code>
          </span>
          <span className="muted">
            workflow <code>{wfId}</code>
          </span>
          <span className={`badge ${streamDone ? "badge--ok" : "badge--unknown"}`}>
            {streamDone ? "stream closed" : "live"}
          </span>
          {onBack && (
            <button className="btn btn--ghost" onClick={onBack}>
              Back to editor
            </button>
          )}
        </div>
        <p className="muted">
          The stored graph lighting up as the interpreter walks it. Click a node
          to open the run drawer (events, tree and cost).
        </p>
        {notFound ? (
          <p className="notice warn">
            Run or workflow not found, or not in your visibility scope.
          </p>
        ) : (
          <>
            {detail.error && !isNotFound(detail.error) && (
              <p className="error">Workflow: {detail.error}</p>
            )}
            {streamError && !isNotFound(streamError) && (
              <p className="error">Stream: {streamError}</p>
            )}
          </>
        )}
      </div>

      {!notFound && (
        <div className="wf-canvas">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            onNodeClick={() => openRun(runId)}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable={false}
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background color="var(--dot-color)" />
            <Controls showInteractive={false} />
            <MiniMap pannable zoomable />
          </ReactFlow>
        </div>
      )}
    </div>
  );
}
