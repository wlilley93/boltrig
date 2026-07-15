import { useMemo, useState } from "react";

import type { AuditNode } from "@/api/types";
import { RunLink } from "@/panels/shared";
import { isNotFound } from "./utils";

function matches(node: AuditNode, needle: string): boolean {
  return [
    node.run_id,
    node.actor ?? "",
    node.tier ?? "",
    ...Object.keys(node.statuses ?? {}),
  ].some((value) => String(value).toLowerCase().includes(needle));
}

export function filterAuditTree(node: AuditNode, query: string): AuditNode | null {
  const needle = query.trim().toLowerCase();
  if (!needle || matches(node, needle)) return node;
  const children = (node.children ?? [])
    .map((child) => filterAuditTree(child, needle))
    .filter((child): child is AuditNode => child !== null);
  return children.length > 0 ? { ...node, children } : null;
}

// Recursive audit-tree node (ported from the old Kanban drawer so the tree
// renders the same everywhere).
function AuditNodeView({ node, root = false }: { node: AuditNode; root?: boolean }) {
  const statuses = node.statuses
    ? Object.entries(node.statuses)
        .map(([s, n]) => `${s}:${n}`)
        .join(" ")
    : "";
  return (
    <li className="audit-node">
      <div className="audit-node__line">
        {root ? <code>{node.run_id}</code> : <RunLink runId={node.run_id} />}
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

export function RunExecutionTree({
  loading,
  error,
  root,
}: {
  loading: boolean;
  error: string | null;
  root: AuditNode | undefined;
}) {
  const [query, setQuery] = useState("");
  const filteredRoot = useMemo(
    () => (root ? filterAuditTree(root, query) : null),
    [root, query],
  );
  return (
    <div className="run-tree">
      <h4>Execution tree</h4>
      {root && (
        <label className="field">
          <span>Filter runs</span>
          <input
            type="search"
            aria-label="Filter execution tree"
            value={query}
            placeholder="Run id, actor, tier, or status"
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
      )}
      {loading && <p className="muted">Loading...</p>}
      {error && !isNotFound(error) && <p className="error">{error}</p>}
      {root && !filteredRoot && (
        <p className="muted">No runs match this filter.</p>
      )}
      {filteredRoot && (
        <ul className="audit-tree audit-tree--root">
          <AuditNodeView node={filteredRoot} root />
        </ul>
      )}
    </div>
  );
}
