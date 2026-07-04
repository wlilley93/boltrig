import type { AuditNode } from "@/api/types";
import { isNotFound } from "./utils";

// Recursive audit-tree node (ported from the old Kanban drawer so the tree
// renders the same everywhere).
function AuditNodeView({ node }: { node: AuditNode }) {
  const statuses = node.statuses
    ? Object.entries(node.statuses)
        .map(([s, n]) => `${s}:${n}`)
        .join(" ")
    : "";
  return (
    <li className="audit-node">
      <div className="audit-node__line">
        <code>{node.run_id}</code>
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
  return (
    <div className="run-tree">
      <h4>Execution tree</h4>
      {loading && <p className="muted">Loading...</p>}
      {error && !isNotFound(error) && <p className="error">{error}</p>}
      {root && (
        <ul className="audit-tree audit-tree--root">
          <AuditNodeView node={root} />
        </ul>
      )}
    </div>
  );
}
