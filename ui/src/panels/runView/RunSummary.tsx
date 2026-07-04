import type { AuditNode } from "@/api/types";

export function RunSummary({
  root,
  statuses,
}: {
  root: AuditNode | undefined;
  statuses: string;
}) {
  if (!root) return null;
  return (
    <div className="kv">
      {root.actor ? <span className="muted">{root.actor}</span> : null}
      {root.tier ? <span className="badge">{root.tier}</span> : null}
      {statuses ? <span className="muted">[{statuses}]</span> : null}
      {typeof root.total_cost_micros === "number" ? (
        <span className="muted">cost: {root.total_cost_micros}µ</span>
      ) : null}
    </div>
  );
}
