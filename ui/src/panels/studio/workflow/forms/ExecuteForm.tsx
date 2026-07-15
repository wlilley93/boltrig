import { useState } from "react";

import type { WorkflowRunRecord } from "@/api/types";
import {
  CodeBlock,
  RunLink,
  errText,
  parseJson,
  runBadgeClass,
  stepBadgeClass,
} from "@/panels/shared";
import { Field, Select } from "@/panels/ux";
import { PendingHumanCard } from "@/panels/uxFlow/pendingHumanCard";
import { useControlMutation } from "@/panels/uxFlow/useControlMutation";
import type { WfFormProps } from "@/panels/studio/workflow/types";

interface ExecuteResultProps {
  result: WorkflowRunRecord;
}

function ExecuteResult({ result }: ExecuteResultProps) {
  return (
    <div className="stack">
      <div className="kv">
        <span className={`badge ${runBadgeClass(result.status)}`}>
          {result.status}
        </span>
        <RunLink runId={result.run_id} />
        <span className="muted">
          {result.workflow_id} v{result.version}
        </span>
      </div>
      {result.steps.length === 0 ? (
        <p className="muted">No steps.</p>
      ) : (
        <ul className="verb-list">
          {result.steps.map((s, i) => (
            <li className="verb-row" key={`${s.id}-${i}`}>
              <div className="verb-row__main">
                <code className="verb-row__id">{s.id}</code>
                {s.action && <span className="muted">{s.action}</span>}
                <span className={`badge ${stepBadgeClass(s.status)}`}>
                  {s.status}
                </span>
              </div>
              {s.reason && (
                <div className="verb-row__meta">
                  <span className="muted">reason: {s.reason}</span>
                </div>
              )}
              {s.output !== undefined && <CodeBlock value={s.output} />}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function ExecuteForm({ wfOptions }: WfFormProps) {
  const [execId, setExecId] = useState("");
  const [execInputs, setExecInputs] = useState("{}");
  const [execError, setExecError] = useState<string | null>(null);
  const [execResult, setExecResult] = useState<WorkflowRunRecord | null>(null);
  const mutation = useControlMutation({
    verb: "control.workflow.execute",
    onApplied(output) {
      setExecResult(output as WorkflowRunRecord);
    },
  });

  async function execute() {
    if (!execId.trim()) {
      setExecError("workflow id is required.");
      return;
    }
    let parsedInputs: Record<string, unknown>;
    try {
      parsedInputs = parseJson<Record<string, unknown>>(execInputs, {});
    } catch (err) {
      setExecError(`inputs: ${errText(err)}`);
      return;
    }
    setExecError(null);
    setExecResult(null);
    await mutation.invoke({ workflow_id: execId.trim(), inputs: parsedInputs });
  }

  return (
    <div className="form">
      <div className="form__title">Execute (run steps)</div>
      <Field label="Workflow" hint="The workflow to run step-by-step now.">
        <Select value={execId} ariaLabel="Workflow" onChange={setExecId} options={wfOptions} />
      </Field>
      <Field label="Inputs (JSON)" hint="Values passed into the workflow." example='{"ticket_id": "4821"}'>
        <textarea
          className="code"
          value={execInputs}
          onChange={(e) => setExecInputs(e.target.value)}
        />
      </Field>
      {mutation.pending && (
        <PendingHumanCard
          hitlRequestId={mutation.pending.id}
          noun="control"
          verb="control.workflow.execute"
          sentParams={mutation.pending.params}
          onApplied={mutation.onPendingApplied}
          onDenied={mutation.onPendingDenied}
          onReset={mutation.resetPending}
        />
      )}
      <div className="form__actions">
        <button
          className="btn btn--primary"
          disabled={mutation.busy || mutation.pending !== null}
          onClick={execute}
        >
          {mutation.busy ? "..." : "Execute"}
        </button>
        {(execError ?? mutation.error) && (
          <span className="error">{execError ?? mutation.error}</span>
        )}
      </div>
      {execResult && <ExecuteResult result={execResult} />}
    </div>
  );
}
