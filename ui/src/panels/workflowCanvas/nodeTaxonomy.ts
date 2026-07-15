// Visual node taxonomy for the automations canvas (design brief sec 22.5 + #51).
// Maps each node "kind" to display metadata (color, icon, label, blurb) and
// groups them into the four drawer categories. Pure data + lookups, no JSX.

export type NodeVisualKind =
  | "trigger"
  | "agent-call"
  | "end"
  | "conditional"
  | "code"
  | "loop"
  | "knowledge"
  | "http"
  | "database"
  | "tool"
  | "notify"
  | "template";

// Retained for loaded legacy definitions. New catalogue nodes never invent an
// agent target: they bind only to verbs the caller can actually discover.
export const BOLT_AGENT_ID = "bolt";

export interface NodeKindMeta {
  kind: NodeVisualKind;
  name: string;
  desc: string;
  color: string;
  icon: string;
}

export interface NodeCategory {
  id: string;
  label: string;
  items: NodeKindMeta[];
}

export const CATEGORIES: NodeCategory[] = [
  {
    id: "common",
    label: "Common",
    items: [
      { kind: "trigger", name: "Start", desc: "Workflow entry trigger", color: "#E8B339", icon: "bolt" },
      { kind: "agent-call", name: "Ask user", desc: "Pause for a governed human answer", color: "#5E69DD", icon: "agent" },
      { kind: "end", name: "End", desc: "Terminal output", color: "#7E95B0", icon: "end" },
    ],
  },
  {
    id: "logic",
    label: "Logic",
    items: [
      { kind: "conditional", name: "Conditional", desc: "IF/ELSE branch", color: "#3DD3F0", icon: "branch" },
      { kind: "code", name: "Code", desc: "Run a script", color: "#E8B339", icon: "code" },
      { kind: "loop", name: "Loop", desc: "Iterate over items", color: "#FF7A45", icon: "loop" },
    ],
  },
  {
    id: "data",
    label: "Data",
    items: [
      { kind: "knowledge", name: "Knowledge", desc: "RAG retrieval", color: "#3FB984", icon: "book" },
      { kind: "http", name: "HTTP", desc: "API request", color: "#7C8BFF", icon: "globe" },
      { kind: "database", name: "Database", desc: "Query / write", color: "#3DD3F0", icon: "cylinder" },
    ],
  },
  {
    id: "integration",
    label: "Integration",
    items: [
      { kind: "tool", name: "Tool", desc: "External tool", color: "#FF7A45", icon: "wrench" },
      { kind: "notify", name: "Notify", desc: "Send notification", color: "#E8B339", icon: "bell" },
      { kind: "template", name: "Template", desc: "Text transform", color: "#7C8BFF", icon: "template" },
    ],
  },
];

const KIND_INDEX: Map<NodeVisualKind, NodeKindMeta> = new Map(
  CATEGORIES.flatMap((c) => c.items).map((m) => [m.kind, m]),
);

// The canvas default visual kind when nothing else is known (replaces the old
// "LLM" node per decision #51).
export const DEFAULT_NODE_KIND: NodeVisualKind = "agent-call";

export function findKind(kind: string | undefined | null): NodeKindMeta | undefined {
  if (!kind) return undefined;
  return KIND_INDEX.get(kind as NodeVisualKind);
}

export function allKinds(): NodeKindMeta[] {
  return CATEGORIES.flatMap((c) => c.items);
}

export const CONTROL_NODE_KINDS = new Set<NodeVisualKind>([
  "trigger",
  "end",
  "conditional",
  "loop",
]);

// The action + seed params a freshly dropped node of this kind carries.
// Control nouns (trigger/flow/code) are resolved LOCALLY by the workflow
// interpreter (boltrig/workflows/control_flow.py): trigger.start/flow.end are
// no-ops, flow.branch is a real conditional with branch-gated children,
// flow.loop records its item count, code.run is recognised-but-disabled (no
// sandbox). The capability nouns (agent/knowledge/http/database/tool/notify/
// template) dispatch through kernel.invoke and need a registered adapter verb;
// until one is bound they record as a soft skip rather than crashing the run.
export function defaultActionForKind(kind: NodeVisualKind): {
  action: string;
  params: Record<string, unknown>;
} {
  switch (kind) {
    case "trigger":
      return { action: "trigger.start", params: {} };
    case "end":
      return { action: "flow.end", params: {} };
    case "agent-call":
      return { action: "chat.ask_user", params: { prompt: "" } };
    case "conditional":
      return { action: "flow.branch", params: {} };
    case "code":
      return { action: "code.run", params: {} };
    case "loop":
      return { action: "flow.loop", params: {} };
    case "knowledge":
      return { action: "knowledge.query", params: {} };
    case "http":
      return { action: "http.request", params: {} };
    case "database":
      return { action: "database.query", params: {} };
    case "tool":
      return { action: "tool.invoke", params: {} };
    case "notify":
      return { action: "notify.send", params: {} };
    case "template":
      return { action: "template.render", params: {} };
    default:
      return { action: "agent.call", params: { agent: BOLT_AGENT_ID } };
  }
}

// Legacy engine kind ("agent" | "service" | "kernel-run") derived from the visual
// kind, used to keep the existing StepNodeData.kind field populated for nodes
// that do not map to a real registry verb.
export function kindFromVisual(kind: NodeVisualKind | undefined): "agent" | "service" | "kernel-run" {
  switch (kind) {
    case "agent-call":
      return "agent";
    case "http":
    case "database":
    case "tool":
    case "knowledge":
      return "service";
    default:
      return "kernel-run";
  }
}

import type { VerbInfo } from "@/api/types";

// Preferred REAL verb for each CAPABILITY kind. Control kinds (trigger/flow/code)
// are resolved locally by the interpreter, so they are not listed here. When the
// canvas verb catalogue (api.capabilities()) contains the preferred verb, a
// dropped node binds to it so the workflow actually executes; otherwise it falls
// back to the synthetic default. Tuned to the default adapter set (ms-graph,
// jira, channel-send, web-fetch, memory, control-plane).
export const PREFERRED_VERB_FOR_KIND: Partial<Record<NodeVisualKind, string>> = {
  "agent-call": "chat.ask_user",
  notify: "channel.send",
  http: "web.fetch",
  knowledge: "memory.recall",
  database: "ticket.search",
  tool: "web.fetch",
};

export function resolveVerbForKind(
  kind: NodeVisualKind,
  verbsById: Map<string, VerbInfo>,
): { action: string; params: Record<string, unknown> } | undefined {
  const preferred = PREFERRED_VERB_FOR_KIND[kind];
  if (preferred && verbsById.has(preferred)) {
    const params: Record<string, unknown> =
      kind === "agent-call" ? { prompt: "" } : {};
    return { action: preferred, params };
  }
  return undefined;
}

export function isNodeKindAvailable(
  kind: NodeVisualKind,
  verbsById: Map<string, VerbInfo>,
): boolean {
  return CONTROL_NODE_KINDS.has(kind) || resolveVerbForKind(kind, verbsById) !== undefined;
}

export function categoriesForCatalogue(verbsById: Map<string, VerbInfo>): NodeCategory[] {
  return CATEGORIES
    .map((category) => ({
      ...category,
      items: category.items.filter((item) => isNodeKindAvailable(item.kind, verbsById)),
    }))
    .filter((category) => category.items.length > 0);
}
