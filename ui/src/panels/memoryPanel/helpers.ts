import type { Option } from "../ux";

export type MemoryTab = "recall" | "browse" | "remember" | "ingest";

export const MEMORY_TABS: ReadonlyArray<{ id: MemoryTab; label: string }> = [
  { id: "recall", label: "Recall" },
  { id: "browse", label: "Browse" },
  { id: "remember", label: "Remember" },
  { id: "ingest", label: "Ingest" },
];

export const KIND_OPTIONS: Option[] = [
  { value: "entity", label: "Entity (a person or thing)" },
  { value: "relationship", label: "Relationship (a link between two)" },
  { value: "summary", label: "Summary" },
  { value: "document_chunk", label: "Document chunk" },
];

export const KIND_FILTER_OPTIONS: Option[] = [
  { value: "", label: "Any type" },
  ...KIND_OPTIONS,
];

export const SOURCE_KIND_OPTIONS: Option[] = [
  { value: "document", label: "Document" },
  { value: "conversation", label: "Conversation" },
  { value: "verb_result", label: "Verb result" },
  { value: "feedback", label: "Feedback" },
];

export const RECALL_MODE_OPTIONS: Option[] = [
  { value: "graph_completion", label: "Connections (default)" },
  { value: "similarity", label: "Similarity" },
];

export function isDenied(res: { status?: string }): boolean {
  return res.status === "error" || res.status === "denied";
}

export function denialText(reason?: string): string {
  if (!reason || reason === "binding_not_found") return "memory not enabled";
  return reason;
}
