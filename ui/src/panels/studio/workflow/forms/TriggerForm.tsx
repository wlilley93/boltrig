import { useState } from "react";

import type { WorkflowRunDescriptor } from "@/api/types";
import { CodeBlock, RunLink, errText, parseJson } from "@/panels/shared";
import { Field, Select } from "@/panels/ux";
import {
  outputRecord,
  PendingHumanCard,
  useControlMutation,
} from "@/panels/uxFlow";
import type { WfFormProps } from "@/panels/studio/workflow/types";

interface TriggerResultProps {
  result: WorkflowRunDescriptor;
}

function TriggerResult({ result }: TriggerResultProps) {
  return (
    <div className="stack">
      <div className="kv">
        <span className="badge">engine: {result.engine}</span>
        <span
          className={`badge ${result.durable ? "badge--activated" : "badge--inert"}`}
        >
          {result.durable ? "durable" : "in-process"}
        </span>
        {result.status && <span className="badge">{result.status}</span>}
        {result.run_id && <RunLink runId={result.run_id} />}
      </div>
      <CodeBlock value={result} />
    </div>
  );
}

export function TriggerForm({ wfOptions }: WfFormProps) {
  const [trigId, setTrigId] = useState("");
  const [inputs, setInputs] = useState("{}");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [trigResult, setTrigResult] = useState<WorkflowRunDescriptor | null>(
    null,
  );
  const mutation = useControlMutation({
    verb: "control.workflow.trigger",
    onApplied: (output) =>
      setTrigResult(outputRecord(output) as WorkflowRunDescriptor),
  });

  async function trigger() {
    if (!trigId.trim()) {
      setValidationError("workflow id is required.");
      return;
    }
    let parsedInputs: Record<string, unknown>;
    try {
      parsedInputs = parseJson<Record<string, unknown>>(inputs, {});
    } catch (err) {
      setValidationError(`inputs: ${errText(err)}`);
      return;
    }
    setValidationError(null);
    setTrigResult(null);
    await mutation.invoke({ workflow_id: trigId.trim(), inputs: parsedInputs });
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
      {mutation.pending && (
        <PendingHumanCard
          hitlRequestId={mutation.pending.id}
          noun="control"
          verb="control.workflow.trigger"
          sentParams={mutation.pending.params}
          onApplied={mutation.onPendingApplied}
          onDenied={mutation.onPendingDenied}
          onReset={mutation.resetPending}
        />
      )}
      <div className="form__actions">
        <button
          className="btn"
          disabled={mutation.busy || mutation.pending !== null}
          onClick={trigger}
        >
          {mutation.busy ? "..." : "Trigger"}
        </button>
        {(validationError ?? mutation.error) && (
          <span className="error">{validationError ?? mutation.error}</span>
        )}
      </div>
      {trigResult && <TriggerResult result={trigResult} />}
    </div>
  );
}
