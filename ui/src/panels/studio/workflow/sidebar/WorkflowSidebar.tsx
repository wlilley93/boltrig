import type { WorkflowSummary } from "@/api/types";
import { listToCsv } from "@/panels/shared";
import type { SidebarProps } from "@/panels/studio/workflow/types";
import { VerbPalette } from "@/panels/studio/workflow/sidebar/VerbPalette";

interface WorkflowListItemProps {
  workflow: WorkflowSummary;
}

function WorkflowListItem({ workflow }: WorkflowListItemProps) {
  return (
    <div className="row-line">
      <div>
        <code>{workflow.id}</code> <span className="muted">v{workflow.version}</span>
      </div>
      <div className="kv">
        <span className="badge">{workflow.source}</span>
        {workflow.intent_tags.length > 0 && (
          <span className="muted">{listToCsv(workflow.intent_tags)}</span>
        )}
      </div>
    </div>
  );
}

export function WorkflowSidebar({ workflows, caps }: SidebarProps) {
  const list: WorkflowSummary[] = workflows.data?.workflows ?? [];
  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>Workflows</h3>
        <button className="btn" onClick={() => workflows.reload()}>Refresh</button>
      </div>
      <div className="list-card__body">
        {workflows.loading && !workflows.data && <p className="muted">Loading...</p>}
        {workflows.error && <p className="error">Failed to load: {workflows.error}</p>}
        {!workflows.loading && list.length === 0 && <p className="muted">No workflows yet.</p>}
        {list.map((w) => <WorkflowListItem workflow={w} key={`${w.id}@${w.version}`} />)}
      </div>

      <VerbPalette caps={caps} />
    </div>
  );
}
