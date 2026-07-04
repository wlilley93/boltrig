import { useState } from "react";

import { WorkflowCanvas } from "@/panels/WorkflowCanvas";
import { WorkflowForm } from "@/panels/studio/workflow/WorkflowForm";

// View toggle inside the Workflow Studio: the existing form flow or the new
// React Flow canvas. Both round-trip the same definition.steps shape.
type WorkflowView = "form" | "canvas";

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
