import { useState } from "react";

import { api } from "../../api/client";
import type {
  CapabilitiesResponse,
  WorkflowSummary,
  WorkflowsResponse,
} from "../../api/types";
import { useFetch, type FetchState } from "../../useFetch";
import { listToCsv } from "../shared";
import { WorkflowCanvas } from "../WorkflowCanvas";
import { ExecuteForm } from "./workflow/forms/ExecuteForm";
import { VerbPalette } from "./workflow/sidebar/VerbPalette";
import { RunsForm } from "./workflow/forms/RunsForm";
import { ScheduleForm } from "./workflow/forms/ScheduleForm";
import { TriggerForm } from "./workflow/forms/TriggerForm";
import { UpsertWorkflowForm } from "./workflow/forms/UpsertWorkflowForm";

// View toggle inside the Workflow Studio: the existing form flow or the new
// React Flow canvas. Both round-trip the same definition.steps shape.
type WorkflowView = "form" | "canvas";

// A ready-made {value,label} for the shared Select. The four action forms all
// pick from the same list of workflow ids, so the parent computes it once.
type WorkflowOption = { value: string; label: string };

// The right rail: the workflows list card, with the verb palette nested inside
// it (the original markup nests the palette within the workflows list-card).
function WorkflowSidebar({
  workflows,
  caps,
}: {
  workflows: FetchState<WorkflowsResponse>;
  caps: FetchState<CapabilitiesResponse>;
}) {
  const list: WorkflowSummary[] = workflows.data?.workflows ?? [];
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
          <div className="row-line" key={`${w.id}@${w.version}`}>
            <div>
              <code>{w.id}</code> <span className="muted">v{w.version}</span>
            </div>
            <div className="kv">
              <span className="badge">{w.source}</span>
              {w.intent_tags.length > 0 && (
                <span className="muted">{listToCsv(w.intent_tags)}</span>
              )}
            </div>
          </div>
        ))}
      </div>

      <VerbPalette caps={caps} />
    </div>
  );
}

function WorkflowForm() {
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

// The Workflow Studio wraps the form flow and the canvas behind a view toggle.
// Both speak the identical definition.steps contract, so an author can build a
// workflow visually or by hand and Save either way.
export function WorkflowStudio() {
  const [view, setView] = useState<WorkflowView>("form");

  return (
    <div className="stack">
      <div className="subtabs" role="tablist" aria-label="Workflow view">
        <button
          className={`subtab ${view === "form" ? "subtab--active" : ""}`}
          onClick={() => setView("form")}
        >
          Form
        </button>
        <button
          className={`subtab ${view === "canvas" ? "subtab--active" : ""}`}
          onClick={() => setView("canvas")}
        >
          Canvas
        </button>
      </div>
      {view === "form" ? <WorkflowForm /> : <WorkflowCanvas />}
    </div>
  );
}
