// The routine canvas: the saved spec drawn as the DAG the engine walks. Every
// visual element is a field the kernel reads — wires are parents[], dashed arms
// are branch:"false", dashed enclosures are computed loop bodies — so the
// drawing cannot disagree with the data. Positions from dragging are session
// chrome only: writing x/y into the governed definition would turn a cosmetic
// nudge into a versioned spec change needing authoring approval, so layout is
// always derivable from the spec alone (same grid as the picker thumbnail).

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";
import type { VerbInfo, WorkflowStepResult } from "@wlilley93/boltrig-web-sdk";

import {
  isPreservedUnsupportedStep,
  loopBodyStepIds,
  type WorkflowStepDraft,
} from "../../workflowDraft";
import { layoutGrid } from "../RoutineThumb";
import type { GraphProblem } from "./graphChecks";
import "./routine.css";

export type CanvasMode = "edit" | "last" | "try";

export interface TryWalkState {
  states: Map<string, "ok" | "skipped">;
  labels: Map<string, string>;
}

export interface CanvasEdgeRef {
  from: string;
  to: string;
}

export const NODE_W = 216;
export const NODE_H = 76;
const COL_W = 272;
const ROW_H = 132;
const ORIGIN_X = 48;
const ORIGIN_Y = 44;

export type StepKind = "trigger" | "branch" | "loop" | "end" | "code" | "act";

export function stepKind(action: string): StepKind {
  if (action.startsWith("trigger.")) return "trigger";
  if (action === "flow.branch") return "branch";
  if (action === "flow.loop") return "loop";
  if (action === "flow.end") return "end";
  if (action.startsWith("code.")) return "code";
  return "act";
}

const KIND_PATHS: Record<StepKind, string[]> = {
  trigger: ["M13 2 L4 14 L11 14 L10 22 L20 9 L13 9 Z"],
  branch: ["M6 4 v6 a4 4 0 0 0 4 4 h8", "M6 4 v16", "M15 11 l3 3 -3 3"],
  loop: ["M17 2 l4 4 -4 4", "M3 11 v-1 a4 4 0 0 1 4 -4 h14", "M7 22 l-4 -4 4 -4", "M21 13 v1 a4 4 0 0 1 -4 4 H3"],
  end: ["M5 5 h14 v14 H5 Z"],
  code: ["M8 6 l-5 6 5 6", "M16 6 l5 6 -5 6"],
  act: ["M4 7 h16 v13 H4 Z", "M4 7 l2 -3 h12 l2 3"],
};

export function StepKindIcon({ kind, size = 15 }: { kind: StepKind; size?: number }) {
  return (
    <svg
      aria-hidden
      fill="none"
      height={size}
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.7"
      viewBox="0 0 24 24"
      width={size}
    >
      {KIND_PATHS[kind].map((d) => <path d={d} key={d} />)}
    </svg>
  );
}

interface NodeChrome {
  chip: string;
  chipTone: "" | "amber" | "red" | "green";
  subline: string;
  dim: boolean;
  dash: boolean;
  outline: "" | "accent" | "red" | "amber";
}

export interface RoutineCanvasProps {
  /** Resets drag positions when it changes (one layout per routine). */
  layoutKey: string;
  steps: WorkflowStepDraft[];
  verbById: Map<string, VerbInfo>;
  mode: CanvasMode;
  selectedStepId: string | null;
  selectedEdge: CanvasEdgeRef | null;
  problems: GraphProblem[];
  runSteps: Map<string, WorkflowStepResult> | null;
  tryWalk: TryWalkState | null;
  /** Read-only definition: selection and zoom only, no mutation. */
  locked: boolean;
  onSelectStep(id: string | null): void;
  onSelectEdge(edge: CanvasEdgeRef | null): void;
  onLinkSteps(from: string, to: string): void;
  onRemoveEdge(from: string, to: string): void;
  onAddAfter(id: string): void;
  onRemoveStep(id: string): void;
  onDuplicateStep(id: string): void;
  onRequestSave(): void;
}

interface DragState {
  id: string;
  originX: number;
  originY: number;
  startX: number;
  startY: number;
  moved: boolean;
}

interface LinkState {
  from: string;
  x: number;
  y: number;
}

export function RoutineCanvas(props: RoutineCanvasProps) {
  const {
    layoutKey,
    steps,
    verbById,
    mode,
    selectedStepId,
    selectedEdge,
    problems,
    runSteps,
    tryWalk,
    locked,
    onSelectStep,
    onSelectEdge,
    onLinkSteps,
    onRemoveEdge,
    onAddAfter,
    onRemoveStep,
    onDuplicateStep,
    onRequestSave,
  } = props;

  const wrapRef = useRef<HTMLDivElement | null>(null);
  const layerRef = useRef<HTMLDivElement | null>(null);
  const suppressClick = useRef(false);
  const hoverRef = useRef<string | null>(null);
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>({});
  const [drag, setDrag] = useState<DragState | null>(null);
  const [linking, setLinking] = useState<LinkState | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);

  useEffect(() => {
    setPositions({});
    setDrag(null);
    setLinking(null);
    setZoom(1);
  }, [layoutKey]);

  const grid = useMemo(() => layoutGrid(
    steps.map((step) => ({ id: step.id.trim(), parents: step.parents })),
  ), [steps]);

  const positionOf = useCallback((id: string) => {
    const dragged = positions[id];
    if (dragged) return dragged;
    const cell = grid.get(id) ?? { col: 0, row: 0 };
    return {
      x: ORIGIN_X + cell.col * COL_W,
      y: ORIGIN_Y + cell.row * ROW_H,
    };
  }, [grid, positions]);

  const byId = useMemo(
    () => new Map(steps.map((step) => [step.id.trim(), step])),
    [steps],
  );
  const problemTone = useMemo(() => {
    const tones = new Map<string, "red" | "amber">();
    for (const problem of problems) {
      if (problem.tone === "red" || !tones.has(problem.stepId)) {
        tones.set(problem.stepId, problem.tone);
      }
    }
    return tones;
  }, [problems]);

  const loopBoxes = useMemo(() => steps
    .filter((step) => step.action === "flow.loop")
    .map((loop) => ({
      loopId: loop.id.trim(),
      body: loopBodyStepIds(steps, loop.id.trim()),
    }))
    .filter((entry) => entry.body.length > 0), [steps]);

  // Canvas extents grow with content; the stage bands cover every used column.
  const columnCount = useMemo(() => {
    let max = 0;
    for (const cell of grid.values()) max = Math.max(max, cell.col);
    return max + 1;
  }, [grid]);
  let canvasW = 720;
  let canvasH = 340;
  for (const step of steps) {
    const at = positionOf(step.id.trim());
    canvasW = Math.max(canvasW, at.x + NODE_W);
    canvasH = Math.max(canvasH, at.y + NODE_H);
  }
  canvasW += 64;
  canvasH += 64;

  const canvasPoint = useCallback((event: { clientX: number; clientY: number }) => {
    const layer = layerRef.current;
    if (!layer) return null;
    const rect = layer.getBoundingClientRect();
    return {
      x: (event.clientX - rect.left) / zoom,
      y: (event.clientY - rect.top) / zoom,
    };
  }, [zoom]);

  const interactive = mode === "edit" && !locked;

  function onNodeMouseDown(id: string, event: ReactMouseEvent) {
    if (!interactive || event.button !== 0) return;
    const point = canvasPoint(event);
    if (!point) return;
    event.preventDefault();
    const at = positionOf(id);
    setDrag({
      id,
      originX: at.x,
      originY: at.y,
      startX: point.x,
      startY: point.y,
      moved: false,
    });
  }

  function onPortMouseDown(id: string, event: ReactMouseEvent) {
    if (!interactive) return;
    event.preventDefault();
    event.stopPropagation();
    const point = canvasPoint(event);
    if (point) setLinking({ from: id, x: point.x, y: point.y });
  }

  function onWrapMouseMove(event: ReactMouseEvent) {
    const point = canvasPoint(event);
    if (!point) return;
    if (drag) {
      const dx = point.x - drag.startX;
      const dy = point.y - drag.startY;
      if (!drag.moved && Math.abs(dx) + Math.abs(dy) < 4) return;
      const snap = (value: number) => Math.max(8, Math.round(value / 8) * 8);
      if (!drag.moved) setDrag({ ...drag, moved: true });
      setPositions((current) => ({
        ...current,
        [drag.id]: { x: snap(drag.originX + dx), y: snap(drag.originY + dy) },
      }));
    } else if (linking) {
      setLinking({ ...linking, x: point.x, y: point.y });
    }
  }

  function onWrapMouseUp(event: ReactMouseEvent) {
    if (linking) {
      let over = hoverRef.current;
      if (!over && typeof document.elementFromPoint === "function") {
        const target = document.elementFromPoint(event.clientX, event.clientY);
        const hit = target?.closest?.("[data-step]");
        if (hit) over = hit.getAttribute("data-step");
      }
      if (over && over !== linking.from) onLinkSteps(linking.from, over);
      setLinking(null);
      return;
    }
    if (drag) {
      if (drag.moved) {
        // Swallow only the click this mouseup produces; a drag that ends over
        // empty canvas must not eat the next genuine click on a node.
        suppressClick.current = true;
        setTimeout(() => { suppressClick.current = false; }, 0);
      }
      setDrag(null);
    }
  }

  function onWrapMouseDown(event: ReactMouseEvent) {
    const target = event.target as HTMLElement;
    if (target === event.currentTarget || target.dataset?.canvas === "1") {
      onSelectStep(null);
      onSelectEdge(null);
    }
  }

  function onNodeClick(id: string) {
    if (suppressClick.current) {
      suppressClick.current = false;
      return;
    }
    onSelectStep(id);
  }

  const zoomBy = (delta: number) => setZoom((current) => (
    Math.min(1.4, Math.max(0.4, Math.round((current + delta) * 100) / 100))
  ));
  const zoomFit = useCallback(() => {
    const wrap = wrapRef.current;
    if (!wrap || wrap.clientWidth === 0 || wrap.clientHeight === 0) {
      setZoom(1);
      return;
    }
    const fit = Math.min(
      1,
      (wrap.clientWidth - 24) / canvasW,
      (wrap.clientHeight - 24) / canvasH,
    );
    setZoom(Math.max(0.4, Math.round(fit * 100) / 100));
  }, [canvasW, canvasH]);

  // Delete/duplicate/save shortcuts, ignored while typing in a field. The
  // listener mutates through the same callbacks as the pointer chrome, so
  // locked definitions and preserved steps refuse identically.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName ?? "";
      if (["INPUT", "TEXTAREA", "SELECT"].includes(tag) || target?.isContentEditable) return;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        onRequestSave();
        return;
      }
      if (!interactive) return;
      // Single-key destructive shortcuts act only while focus sits on the
      // canvas itself (or nowhere): Delete on a rail or zoom button must not
      // remove the selected step.
      const inCanvas = target ? wrapRef.current?.contains(target) ?? false : false;
      if (!inCanvas && target !== document.body) return;
      if (event.key === "Backspace" || event.key === "Delete") {
        if (selectedEdge) {
          event.preventDefault();
          onRemoveEdge(selectedEdge.from, selectedEdge.to);
        } else if (selectedStepId) {
          event.preventDefault();
          onRemoveStep(selectedStepId);
        }
        return;
      }
      if (event.key === "d" && !event.metaKey && !event.ctrlKey && selectedStepId) {
        event.preventDefault();
        onDuplicateStep(selectedStepId);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [
    interactive,
    selectedEdge,
    selectedStepId,
    onRemoveEdge,
    onRemoveStep,
    onDuplicateStep,
    onRequestSave,
  ]);

  // --- per-node presentation ------------------------------------------------

  function chromeFor(step: WorkflowStepDraft): NodeChrome {
    const id = step.id.trim();
    const action = step.action.trim();
    const kind = stepKind(action);
    const verb = verbById.get(action);
    const chrome: NodeChrome = {
      chip: "",
      chipTone: "",
      subline: action || "nothing set yet",
      dim: kind === "code",
      dash: false,
      outline: "",
    };

    if (mode === "last") {
      const record = runSteps?.get(id);
      if (record) {
        chrome.chip = record.status;
        chrome.chipTone = record.status === "ok"
          ? "green"
          : record.status === "failed" || record.status === "error"
            ? "red"
            : record.status === "skipped"
              ? ""
              : "amber";
        chrome.subline = record.reason ?? action ?? "";
        chrome.dim = record.status === "skipped";
        chrome.dash = record.status === "skipped";
      } else if (runSteps) {
        chrome.chip = "not reached";
        chrome.dim = true;
      }
    } else if (mode === "try") {
      const state = tryWalk?.states.get(id);
      const label = tryWalk?.labels.get(id);
      if (state === "ok") {
        chrome.chip = kind === "branch" && label ? `takes ${label}` : "would run";
        chrome.chipTone = "green";
        chrome.dim = false;
      } else if (state === "skipped") {
        chrome.chip = "skipped";
        chrome.dim = true;
        chrome.dash = true;
      } else {
        chrome.chip = "not reached";
        chrome.dim = true;
      }
    } else {
      if (kind === "code") {
        chrome.chip = "never runs";
        chrome.chipTone = "amber";
      } else if (!action) {
        chrome.chip = "no action yet";
        chrome.chipTone = "amber";
      } else if (verb) {
        const health = typeof verb.health === "string" ? verb.health : "";
        if (health === "down") {
          chrome.chip = "adapter down";
          chrome.chipTone = "red";
        } else if (health === "degraded") {
          chrome.chip = "adapter degraded";
          chrome.chipTone = "amber";
        } else if (verb.consequence === "high") {
          // Approval is decided by policy at run time; consequence is the
          // honest per-verb datum the SDK actually exposes.
          chrome.chip = "high consequence";
          chrome.chipTone = "amber";
        }
      } else if (kind === "act" && verbById.size > 0) {
        chrome.chip = "not in registry";
        chrome.chipTone = "amber";
      }
    }

    const isSelected = selectedStepId === id;
    chrome.outline = isSelected
      ? "accent"
      : mode === "edit"
        ? (problemTone.get(id) ?? "")
        : "";
    return chrome;
  }

  // --- wires ----------------------------------------------------------------

  interface Wire {
    from: string;
    to: string;
    x1: number;
    y1: number;
    x2: number;
    y2: number;
    d: string;
    dashed: boolean;
    faded: boolean;
  }

  const wires: Wire[] = [];
  for (const step of steps) {
    const to = step.id.trim();
    for (const parent of step.parents) {
      if (!byId.has(parent)) continue;
      const fromAt = positionOf(parent);
      const toAt = positionOf(to);
      const x1 = fromAt.x + NODE_W;
      const y1 = fromAt.y + 38;
      const x2 = toAt.x;
      const y2 = toAt.y + 38;
      const targetRun = runSteps?.get(to);
      const faded = (mode === "try" && tryWalk?.states.get(to) !== "ok")
        || (mode === "last" && runSteps !== null && targetRun?.status !== "ok");
      wires.push({
        from: parent,
        to,
        x1,
        y1,
        x2,
        y2,
        d: `M ${x1} ${y1} C ${x1 + 46} ${y1}, ${x2 - 46} ${y2}, ${x2} ${y2}`,
        dashed: step.branchArm === "false",
        faded,
      });
    }
  }

  const branchLabels = wires
    .map((wire) => {
      const child = byId.get(wire.to);
      const parent = byId.get(wire.from);
      if (!child?.branchArm || parent?.action !== "flow.branch") return null;
      const live = mode === "try"
        && tryWalk?.labels.get(wire.from) === child.branchArm;
      return {
        key: `${wire.from}->${wire.to}`,
        text: child.branchArm,
        live,
        left: Math.round((wire.x1 + wire.x2) / 2 - 19),
        top: Math.round((wire.y1 + wire.y2) / 2 - 10),
      };
    })
    .filter((label): label is NonNullable<typeof label> => label !== null);

  const linkSource = linking ? positionOf(linking.from) : null;

  return (
    <div className="rc-canvas-outer">
    <div
      className="rc-wrap"
      onMouseDown={onWrapMouseDown}
      onMouseLeave={onWrapMouseUp}
      onMouseMove={onWrapMouseMove}
      onMouseUp={onWrapMouseUp}
      ref={wrapRef}
    >
      <div
        className="rc-layer"
        data-canvas="1"
        ref={layerRef}
        style={{
          width: canvasW,
          height: canvasH,
          transform: `scale(${zoom})`,
        }}
      >
        {Array.from({ length: columnCount }, (_, column) => (
          <div
            className="rc-stage"
            key={column}
            style={{ left: ORIGIN_X + column * COL_W - 28, width: COL_W }}
          >
            <span>{String(column + 1).padStart(2, "0")}</span>
          </div>
        ))}
        <svg className="rc-wires" height={canvasH} width={canvasW}>
          {wires.map((wire) => {
            const key = `${wire.from}->${wire.to}`;
            const selected = selectedEdge?.from === wire.from
              && selectedEdge?.to === wire.to;
            return (
              <g key={key}>
                <path
                  className="rc-wire-hit"
                  d={wire.d}
                  fill="none"
                  stroke="transparent"
                  strokeWidth={16}
                  onClick={(event) => {
                    event.stopPropagation();
                    onSelectEdge({ from: wire.from, to: wire.to });
                    onSelectStep(null);
                  }}
                >
                  <title>{`${wire.to} waits on ${wire.from}`}</title>
                </path>
                <path
                  d={wire.d}
                  fill="none"
                  stroke={selected
                    ? "var(--accent)"
                    : wire.faded
                      ? "var(--border)"
                      : "var(--border-2)"}
                  strokeDasharray={wire.dashed ? "4 4" : undefined}
                  strokeWidth={selected ? 2.2 : 1.5}
                />
                <circle cx={wire.x1} cy={wire.y1} fill="var(--border-2)" r={2.5} />
                <circle cx={wire.x2} cy={wire.y2} fill="var(--border-2)" r={2.5} />
              </g>
            );
          })}
          {linking && linkSource && (
            <path
              d={`M ${linkSource.x + NODE_W} ${linkSource.y + 38} L ${linking.x} ${linking.y}`}
              fill="none"
              stroke="var(--accent)"
              strokeDasharray="5 4"
              strokeWidth={1.8}
            />
          )}
        </svg>
        {loopBoxes.map(({ loopId, body }) => {
          const points = body
            .map((id) => (byId.has(id) ? positionOf(id) : null))
            .filter((point): point is { x: number; y: number } => point !== null);
          if (points.length === 0) return null;
          const left = Math.min(...points.map((point) => point.x)) - 17;
          const top = Math.min(...points.map((point) => point.y)) - 17;
          const right = Math.max(...points.map((point) => point.x)) + NODE_W + 17;
          const bottom = Math.max(...points.map((point) => point.y)) + NODE_H + 17;
          return (
            <div
              className="rc-loop-box"
              key={loopId}
              style={{ left, top, width: right - left, height: bottom - top }}
            >
              <span>
                {body.length === 1
                  ? "runs once per item"
                  : `${body.length} steps, once per item`}
              </span>
            </div>
          );
        })}
        {branchLabels.map((label) => (
          <span
            className="rc-branch-label"
            data-live={label.live ? "true" : undefined}
            key={label.key}
            style={{ left: label.left, top: label.top }}
          >
            {label.text}
          </span>
        ))}
        {steps.map((step) => {
          const id = step.id.trim();
          const at = positionOf(id);
          const kind = stepKind(step.action.trim());
          const chrome = chromeFor(step);
          const preserved = isPreservedUnsupportedStep(step);
          const showChrome = interactive && !drag && !linking
            && (hovered === id || selectedStepId === id);
          return (
            <div
              className="rc-node"
              data-dim={chrome.dim ? "true" : undefined}
              data-step={id}
              key={`${id}-${step.id}`}
              style={{ left: at.x, top: at.y, width: NODE_W, height: NODE_H, position: "absolute" }}
            >
              <button
                // The label carries the status chip too: what the sighted eye
                // reads off the card must reach assistive tech with it.
                aria-label={`Step ${id || "unnamed"}${chrome.chip ? `, ${chrome.chip}` : ""}`}
                className="rc-node-card"
                data-dash={chrome.dash ? "true" : undefined}
                data-dragging={drag?.id === id ? "true" : undefined}
                data-outline={chrome.outline || undefined}
                onClick={() => onNodeClick(id)}
                onMouseDown={(event) => onNodeMouseDown(id, event)}
                onMouseEnter={() => {
                  hoverRef.current = id;
                  if (!drag && !linking) setHovered(id);
                }}
                onMouseLeave={() => {
                  if (hoverRef.current === id) hoverRef.current = null;
                  if (!drag && !linking) setHovered(null);
                }}
                type="button"
              >
                <span className="rc-node-title-row">
                  <span className="rc-node-icon" data-kind={kind}>
                    <StepKindIcon kind={kind} />
                  </span>
                  <span className="rc-node-title">{id || "unnamed step"}</span>
                </span>
                {(chrome.subline || chrome.chip) && (
                  <span className="rc-node-meta">
                    {chrome.subline && (
                      <span className="rc-node-action">{chrome.subline}</span>
                    )}
                    {chrome.chip && (
                      <span
                        className="rc-node-chip"
                        data-tone={chrome.chipTone || undefined}
                      >
                        {chrome.chip}
                      </span>
                    )}
                  </span>
                )}
              </button>
              {showChrome && kind !== "end" && (
                <>
                  <button
                    aria-label={`Drag to make another step wait on ${id}`}
                    className="rc-node-port"
                    onMouseDown={(event) => onPortMouseDown(id, event)}
                    title="Drag to make another step wait on this one"
                    type="button"
                  >
                    <span />
                  </button>
                  <button
                    aria-label={`Add a step after ${id}`}
                    className="rc-node-plus"
                    onClick={(event) => {
                      event.stopPropagation();
                      onAddAfter(id);
                    }}
                    title="Add a step after this one"
                    type="button"
                  >
                    <svg
                      aria-hidden
                      fill="none"
                      height="11"
                      stroke="currentColor"
                      strokeLinecap="round"
                      strokeWidth="2.5"
                      viewBox="0 0 24 24"
                      width="11"
                    >
                      <line x1="12" x2="12" y1="5" y2="19" />
                      <line x1="5" x2="19" y1="12" y2="12" />
                    </svg>
                  </button>
                </>
              )}
              {showChrome && !preserved && (
                <button
                  aria-label={`Drop ${id} from the canvas`}
                  className="rc-node-plus"
                  onClick={(event) => {
                    event.stopPropagation();
                    onRemoveStep(id);
                  }}
                  style={{ right: -9, top: -9, bottom: "auto" }}
                  title="Drop this step"
                  type="button"
                >
                  ×
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
      <div className="rc-zoom rc-zoom-overlay">
        <button aria-label="Zoom out" onClick={() => zoomBy(-0.1)} type="button">−</button>
        <button
          aria-label="Fit the whole routine"
          className="rc-zoom-fit"
          onClick={zoomFit}
          title="Fit the whole routine"
          type="button"
        >
          {Math.round(zoom * 100)}%
        </button>
        <button aria-label="Zoom in" onClick={() => zoomBy(0.1)} type="button">+</button>
      </div>
    </div>
  );
}
