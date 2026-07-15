import type { WorkItem, WorkStatus } from "@/api/types";

export type WorkView = "project" | "linear" | "board";
export type ConvergentFilter = "all" | "yes" | "no";

export const ALL_STATUSES = "all-statuses";
export const WORK_STATUS_ORDER: WorkStatus[] = [
  "pending",
  "in_flight",
  "blocked",
  "awaiting_human",
  "done",
  "failed",
];

export interface WorkFiltersState {
  query: string;
  status: string;
  owner: string;
  source: string;
  convergent: ConvergentFilter;
}

export interface WorkTreeNode {
  item: WorkItem;
  children: WorkTreeNode[];
}

function normalized(value: string | null | undefined): string {
  return value?.trim().toLowerCase() ?? "";
}

export function ownerFilterValue(value: string | null | undefined): string {
  return value?.trim() ? `owner:${value}` : "owner:none";
}

export function sourceFilterValue(value: string | null | undefined): string {
  return value?.trim() ? `source:${value}` : "source:none";
}

export function ownerOptions(items: ReadonlyArray<WorkItem>): Array<{ value: string; label: string }> {
  const values = new Set(items.map((item) => item.owner_member?.trim() || ""));
  return Array.from(values)
    .sort((a, b) => a.localeCompare(b))
    .map((value) => ({ value: ownerFilterValue(value), label: value || "Unassigned" }));
}

export function sourceOptions(items: ReadonlyArray<WorkItem>): Array<{ value: string; label: string }> {
  const values = new Set(items.map((item) => item.source?.trim() || ""));
  return Array.from(values)
    .sort((a, b) => a.localeCompare(b))
    .map((value) => ({ value: sourceFilterValue(value), label: value || "Unknown source" }));
}

export function filterWorkItems(
  items: ReadonlyArray<WorkItem>,
  filters: WorkFiltersState,
): WorkItem[] {
  const query = normalized(filters.query);
  return items.filter((item) => {
    const searchable = [item.intent, item.id, item.parent_id, item.owner_member, item.source]
      .map(normalized)
      .join(" ");
    return (!query || searchable.includes(query)) &&
      (filters.status === ALL_STATUSES || item.status === filters.status) &&
      (filters.owner === "all-owners" || ownerFilterValue(item.owner_member) === filters.owner) &&
      (filters.source === "all-sources" || sourceFilterValue(item.source) === filters.source) &&
      (filters.convergent === "all" || item.convergent === (filters.convergent === "yes"));
  });
}

export function buildWorkForest(items: ReadonlyArray<WorkItem>): WorkTreeNode[] {
  const nodes = new Map(items.map((item) => [item.id, { item, children: [] as WorkTreeNode[] }]));
  const roots: WorkTreeNode[] = [];
  for (const node of nodes.values()) {
    const parent = node.item.parent_id ? nodes.get(node.item.parent_id) : undefined;
    if (parent && parent !== node) parent.children.push(node);
    else roots.push(node);
  }
  const sortNodes = (values: WorkTreeNode[], seen = new Set<string>()): void => {
    values.sort((a, b) => a.item.intent.localeCompare(b.item.intent));
    for (const value of values) {
      if (seen.has(value.item.id)) {
        value.children = [];
        continue;
      }
      seen.add(value.item.id);
      sortNodes(value.children, new Set(seen));
    }
  };
  sortNodes(roots);
  return roots;
}

export function childCounts(items: ReadonlyArray<WorkItem>): Map<string, number> {
  const counts = new Map<string, number>();
  for (const item of items) {
    if (item.parent_id) counts.set(item.parent_id, (counts.get(item.parent_id) ?? 0) + 1);
  }
  return counts;
}

export function linearWorkItems(items: ReadonlyArray<WorkItem>): WorkItem[] {
  return [...items].sort((a, b) => {
    const status = WORK_STATUS_ORDER.indexOf(a.status) - WORK_STATUS_ORDER.indexOf(b.status);
    return status || a.intent.localeCompare(b.intent);
  });
}
