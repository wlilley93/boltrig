import { FetchError, StatusBadge, WORK_STATUS } from "@/panels/ux";
import { RunLink } from "@/panels/shared";
import type { InsightState } from "./useInsightState";

export function RunsCard({ s }: { s: InsightState }) {
  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>Runs</h3>
        <span className="muted">{s.runRows.length}</span>
      </div>
      <div className="list-card__body">
        {s.runs.loading && !s.runs.data && <p className="muted">Loading...</p>}
        <FetchError error={s.runs.error} status={s.runs.errorStatus} onRetry={s.runs.reload} />
        {!s.runs.loading && s.runRows.length === 0 && (
          <p className="muted">No runs in your scope yet.</p>
        )}
        {s.runRows.map((r) => (
          <div className="row-line" key={r.work_item}>
            <div>
              {r.run_id ? <RunLink runId={r.run_id} /> : <code className="muted">no run</code>}
              <div className="muted">{r.intent}</div>
            </div>
            <div className="kv">
              <StatusBadge value={r.status} glossary={WORK_STATUS} />
              {r.owner && <span className="muted">{r.owner}</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
