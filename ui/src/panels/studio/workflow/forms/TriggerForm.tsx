import { useState } from "react";

import { api } from "@/api/client";
import type { WorkflowRunDescriptor } from "@/api/types";
import { CodeBlock, RunLink, errText, parseJson } from "@/panels/shared";
import { Field, Select } from "@/panels/ux";
import type { WfFormProps } from "@/panels/studio/workflow/types";

export function TriggerForm({ wfOptions }: WfFormProps) {
  const [trigId, setTrigId] = useState("");
  const [inputs, setInputs] = useState("{}");
  const [trigBusy, setTrigBusy] = useState(false);
  const [trigError, setTrigError] = useState<string | null>(null);
  const [trigResult, setTrigResult] = useState<WorkflowRunDescriptor | null>(
    null,
  );

  async function trigger() {
    if (!trigId.trim()) {
      setTrigError("workflow id is required.");
      return;
    }
    let parsedInputs: Record<string, unknown>;
    try {
      parsedInputs = parseJson<Record<string, unknown>>(inputs, {});
    } catch (err) {
      setTrigError(`inputs: ${errText(err)}`);
      return;
    }
    setTrigBusy(true);
    setTrigError(null);
    setTrigResult(null);
    try {
      const res = await api.triggerWorkflow(trigId.trim(), {
        inputs: parsedInputs,
      });
      if (res.error) setTrigError(res.error);
      else setTrigResult(res);
    } catch (err) {
      setTrigError(errText(err));
    } finally {
      setTrigBusy(false);
    }
  }

  return (
    <div className="form">
      <div className="form__title">Trigger</div>
      <Field label="Workflow" hint="The workflow to start now.">
        <Select value={trigId} ariaLabel="Workflow" onChange={setTrigId} options={wfOptions} />
      </Field>
      <Field label="Inputs (JSON)" hint="Values passed into the workflow." example='{"ticket_id": "4821"}'>
        <textarea
          className="code"
          value={inputs}
          onChange={(e) => setInputs(e.target.value)}
        />
      </Field>
      <div className="form__actions">
        <button className="btn" disabled={trigBusy} onClick={trigger}>
          {trigBusy ? "..." : "Trigger"}
        </button>
        {trigError && <span className="error">{trigError}</span>}
      </div>
      {trigResult && (
        <div className="stack">
          <div className="kv">
            <span className="badge">engine: {trigResult.engine}</span>
            <span
              className={`badge ${trigResult.durable ? "badge--activated" : "badge--inert"}`}
            >
              {trigResult.durable ? "durable" : "in-process"}
            </span>
            {trigResult.status && (
              <span className="badge">{trigResult.status}</span>
            )}
            {trigResult.run_id && <RunLink runId={trigResult.run_id} />}
          </div>
          <CodeBlock value={trigResult} />
        </div>
      )}
    </div>
  );
}
