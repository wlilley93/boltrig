import { api } from "@/api/client";
import type { WorkflowSummary } from "@/api/types";
import { useFetch } from "@/useFetch";
import { ExecuteForm } from "@/panels/studio/workflow/forms/ExecuteForm";
import { RunsForm } from "@/panels/studio/workflow/forms/RunsForm";
import { ScheduleForm } from "@/panels/studio/workflow/forms/ScheduleForm";
import { TriggerForm } from "@/panels/studio/workflow/forms/TriggerForm";
import { UpsertWorkflowForm } from "@/panels/studio/workflow/forms/UpsertWorkflowForm";
import { WorkflowSidebar } from "@/panels/studio/workflow/sidebar/WorkflowSidebar";
import type { WorkflowOption } from "@/panels/studio/workflow/types";

export function WorkflowForm() {
  const workflows = useFetch(() => api.workflows(), []);
  const caps = useFetch(() => api.capabilities(), []);

  const list: WorkflowSummary[] = workflows.data?.workflows ?? [];
  const wfOptions: WorkflowOption[] = [
    { value: "", label: "Choose a workflow..." },
    ...list.map((w) => ({ value: w.id, label: w.id })),
  ];

  return (
    <div className="cols">
      <div className="stack">
        <UpsertWorkflowForm onSaved={() => workflows.reload()} />
        <ScheduleForm wfOptions={wfOptions} />
        <TriggerForm wfOptions={wfOptions} />
        <ExecuteForm wfOptions={wfOptions} />
        <RunsForm wfOptions={wfOptions} />
      </div>

      <WorkflowSidebar workflows={workflows} caps={caps} />
    </div>
  );
}
