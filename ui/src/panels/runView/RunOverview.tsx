import type { AuditNode } from "@/api/types";
import { money } from "@/panels/insightPanel/formatting";
import { RunLink } from "@/panels/shared";
import { isNotFound } from "./utils";

function Metric({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="run-overview__metric">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

export function RunOverview({
  root,
  loading,
  error,
}: {
  root: AuditNode | undefined;
  loading: boolean;
  error: string | null;
}) {
  if (loading && !root) return <p className="muted">Loading run summary...</p>;
  if (error && !root && !isNotFound(error)) {
    return <p className="error">Audit summary: {error}</p>;
  }
  if (!root) return <p className="muted">No audit summary is available yet.</p>;

  const cost = root.total_cost_micros ?? root.cost_micros;
  const statuses = Object.entries(root.statuses ?? {});

  return (
    <div className="run-overview">
      <div className="run-overview__head">
        <h4>Run overview</h4>
        <code>{root.run_id}</code>
      </div>
      <dl className="run-overview__metrics">
        {root.actor && <Metric label="Actor">{root.actor}</Metric>}
        {typeof root.parent_run_id === "string" && root.parent_run_id && (
          <Metric label="Parent run">
            <RunLink runId={root.parent_run_id} />
          </Metric>
        )}
        {root.tier && <Metric label="Tier">{root.tier}</Metric>}
        {typeof root.actions === "number" && <Metric label="Actions">{root.actions}</Metric>}
        {typeof root.tokens === "number" && <Metric label="Tokens">{root.tokens}</Metric>}
        {typeof root.depth === "number" && <Metric label="Depth">{root.depth}</Metric>}
        {typeof cost === "number" && (
          <Metric label="Cost">
            <span title={`${cost} micros`}>{money(cost)}</span>
          </Metric>
        )}
      </dl>
      <div className="run-overview__statuses" aria-label="Run status counts">
        <h4>Status</h4>
        {statuses.length === 0 ? (
          <p className="muted">No status receipts yet.</p>
        ) : (
          <div className="kv">
            {statuses.map(([status, count]) => (
              <span className="badge" key={status}>
                <code>{status}</code> {count}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
