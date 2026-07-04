import type { FetchState } from "@/useFetch";
import type { WorkflowSummary, WorkflowsResponse } from "@/api/types";

interface WorkflowListProps {
  workflows: FetchState<WorkflowsResponse>;
  list: WorkflowSummary[];
  onPick: (w: WorkflowSummary) => void;
}

export function WorkflowList({ workflows, list, onPick }: WorkflowListProps) {
  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>Workflows</h3>
        <button className="btn" onClick={() => workflows.reload()}>
          Refresh
        </button>
      </div>
      <div className="list-card__body">
        {workflows.loading && !workflows.data && (
          <p className="muted">Loading...</p>
        )}
        {workflows.error && (
          <p className="error">Failed to load: {workflows.error}</p>
        )}
        {!workflows.loading && list.length === 0 && (
          <p className="muted">No workflows yet.</p>
        )}
        {list.map((w) => (
          <button
            className="row-line palette-row"
            key={`${w.id}@${w.version}`}
            onClick={() => onPick(w)}
            title="Use as the Save / Run target"
          >
            <div>
              <code>{w.id}</code>{" "}
              <span className="muted">v{w.version}</span>
            </div>
            <span className="badge">{w.source}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
