import { useState } from "react";

import { api } from "@/api/client";
import { RunLink, errText } from "@/panels/shared";
import { Field, Select } from "@/panels/ux";
import type { WfFormProps } from "@/panels/studio/workflow/types";

export function RunsForm({ wfOptions }: WfFormProps) {
  const [runsId, setRunsId] = useState("");
  const [runsBusy, setRunsBusy] = useState(false);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [runs, setRuns] = useState<string[] | null>(null);

  async function loadRuns() {
    if (!runsId.trim()) {
      setRunsError("workflow id is required.");
      return;
    }
    setRunsBusy(true);
    setRunsError(null);
    setRuns(null);
    try {
      const res = await api.workflowRuns(runsId.trim());
      setRuns(res.runs);
    } catch (err) {
      setRunsError(errText(err));
    } finally {
      setRunsBusy(false);
    }
  }

  return (
    <div className="form">
      <div className="form__title">View runs</div>
      <div className="form__actions">
        <Field label="Workflow" hint="See past runs of this workflow.">
          <Select value={runsId} ariaLabel="Workflow" onChange={setRunsId} options={wfOptions} />
        </Field>
        <button className="btn" disabled={runsBusy} onClick={loadRuns}>
          {runsBusy ? "..." : "Load runs"}
        </button>
        {runsError && <span className="error">{runsError}</span>}
      </div>
      {runs && (
        <p className="muted">
          {runs.length === 0 ? "No runs." : `${runs.length} run(s):`}{" "}
          {runs.map((r) => <RunLink runId={r} key={r} />)}
        </p>
      )}
    </div>
  );
}
