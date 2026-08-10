import type { WorkflowStepDefinition } from "@wlilley93/boltrig-web-sdk";

// The thumbnail on a routine card is the routine's OWN graph, laid out from the
// saved spec's `parents[]` — the same field the engine reads. It is not a stock
// picture of a flowchart: a routine that fans out looks like it fans out, and a
// routine with one line looks like one line. Drawing anything else here would
// make the picker a decoration rather than a way to recognise a routine.

// Outlines are drawn in --text-3, not --border-2. VDS measured --border-2
// against the thumbnail ground at 1.42:1 in dark and 1.31:1 in light, against
// the 3:1 that WCAG 2.2 SC 1.4.11 requires of a graphical object you must see
// to read the graph. --text-3 is the lightest token that clears it in both
// themes (4.89 and 4.00), so the drawing is a shade firmer than the decided
// target's hairline and legible to the people the floor exists for.
const VIEW_W = 248;
const VIEW_H = 76;
const NODE_W = 34;
const NODE_H = 13;

export interface ThumbNode {
  id: string;
  x: number;
  y: number;
  kind: "trigger" | "code" | "step";
  needsYou: boolean;
}

export interface ThumbEdge { from: ThumbNode; to: ThumbNode }

export interface GridCell { col: number; row: number }

// The same depth-based grid seeds both this thumbnail and the full routine
// canvas, so a routine looks like a bigger version of its own card rather
// than a differently-shaped drawing of the same spec.
export function layoutGrid(
  steps: { id: string; parents?: string[] }[],
): Map<string, GridCell> {
  const byId = new Map(steps.map((step) => [step.id, step]));

  // Depth is the longest path from a root, so a fan-in sits to the right of
  // every branch that feeds it rather than overlapping the shorter one. The
  // seen-set makes a cyclic spec terminate instead of hanging the picker.
  const depthOf = new Map<string, number>();
  function depth(id: string, seen: Set<string>): number {
    const cached = depthOf.get(id);
    if (cached !== undefined) return cached;
    if (seen.has(id)) return 0;
    seen.add(id);
    const step = byId.get(id);
    const parents = (step?.parents ?? []).filter((parent) => byId.has(parent));
    const value = parents.length === 0
      ? 0
      : 1 + Math.max(...parents.map((parent) => depth(parent, seen)));
    seen.delete(id);
    depthOf.set(id, value);
    return value;
  }
  for (const step of steps) depth(step.id, new Set());

  const rowsUsed = new Map<number, number>();
  const cells = new Map<string, GridCell>();
  for (const step of steps) {
    const col = depthOf.get(step.id) ?? 0;
    const row = rowsUsed.get(col) ?? 0;
    rowsUsed.set(col, row + 1);
    cells.set(step.id, { col, row });
  }
  return cells;
}

export function layoutSteps(steps: WorkflowStepDefinition[]): {
  nodes: ThumbNode[];
  edges: ThumbEdge[];
} {
  if (steps.length === 0) return { nodes: [], edges: [] };
  const cells = layoutGrid(steps);

  const columns = new Map<number, WorkflowStepDefinition[]>();
  for (const step of steps) {
    const column = cells.get(step.id)?.col ?? 0;
    const list = columns.get(column) ?? [];
    list.push(step);
    columns.set(column, list);
  }

  const maxDepth = Math.max(...columns.keys());
  const stepX = maxDepth === 0 ? 0 : (VIEW_W - NODE_W) / maxDepth;
  const nodes: ThumbNode[] = [];
  for (const [column, list] of columns) {
    const spacing = VIEW_H / (list.length + 1);
    list.forEach((step, index) => {
      const action = String(step.action ?? "");
      nodes.push({
        id: step.id,
        x: column * stepX,
        y: spacing * (index + 1) - NODE_H / 2,
        kind: action.startsWith("trigger.")
          ? "trigger"
          : action.startsWith("code.")
            ? "code"
            : "step",
        // A step with no action cannot run unattended: the design marks exactly
        // that case with an amber pip rather than a separate legend.
        needsYou: action === "",
      });
    });
  }

  const index = new Map(nodes.map((node) => [node.id, node]));
  const edges: ThumbEdge[] = [];
  for (const step of steps) {
    const to = index.get(step.id);
    if (!to) continue;
    for (const parent of step.parents ?? []) {
      const from = index.get(parent);
      if (from) edges.push({ from, to });
    }
  }
  return { nodes, edges };
}

export function RoutineThumb({ steps }: { steps: WorkflowStepDefinition[] }) {
  const { nodes, edges } = layoutSteps(steps);
  if (nodes.length === 0) {
    return (
      <svg className="routine-graph" viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} role="img"
        aria-label="This routine has no steps yet">
        <text x={VIEW_W / 2} y={VIEW_H / 2} textAnchor="middle" dominantBaseline="middle"
          fill="var(--text-4)" fontSize="10">no steps yet</text>
      </svg>
    );
  }
  return (
    <svg
      aria-label={`${nodes.length} ${nodes.length === 1 ? "step" : "steps"}`}
      className="routine-graph"
      role="img"
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
    >
      {edges.map((edge, i) => (
        <line
          key={i}
          stroke="var(--text-3)"
          strokeWidth="1"
          x1={edge.from.x + NODE_W}
          x2={edge.to.x}
          y1={edge.from.y + NODE_H / 2}
          y2={edge.to.y + NODE_H / 2}
        />
      ))}
      {nodes.map((node) => (
        <g key={node.id}>
          <rect
            fill={node.kind === "trigger" ? "color-mix(in srgb, var(--orange) 22%, transparent)" : "var(--card-2)"}
            height={NODE_H}
            rx="4"
            stroke={node.kind === "trigger" ? "var(--orange)" : "var(--text-3)"}
            strokeDasharray={node.kind === "code" ? "3 2" : undefined}
            strokeWidth="1"
            width={NODE_W}
            x={node.x}
            y={node.y}
          />
          {node.needsYou && (
            <circle cx={node.x + NODE_W - 3} cy={node.y + 3} fill="var(--amber)" r="2" />
          )}
        </g>
      ))}
    </svg>
  );
}
