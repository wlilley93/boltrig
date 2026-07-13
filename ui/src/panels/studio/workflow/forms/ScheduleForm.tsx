import { useState } from "react";

import { CodeBlock } from "@/panels/shared";
import { Field, Select } from "@/panels/ux";
import {
  outputRecord,
  PendingHumanCard,
  useControlMutation,
} from "@/panels/uxFlow";
import { CRON_PRESETS, TZ_OPTIONS } from "@/panels/studio/workflow/constants";
import type { WfFormProps } from "@/panels/studio/workflow/types";

export function ScheduleForm({ wfOptions }: WfFormProps) {
  const [schedId, setSchedId] = useState("");
  const [cron, setCron] = useState("");
  const [tz, setTz] = useState("UTC");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [schedResult, setSchedResult] = useState<unknown>(null);
  const mutation = useControlMutation({
    verb: "control.workflow.schedule",
    onApplied: (output) => setSchedResult(outputRecord(output).schedule),
  });

  async function schedule() {
    if (!schedId.trim() || !cron.trim()) {
      setValidationError("workflow id and cron are required.");
      return;
    }
    setValidationError(null);
    setSchedResult(null);
    await mutation.invoke({
      workflow_id: schedId.trim(),
      cron: cron.trim(),
      timezone: tz.trim() || "UTC",
    });
  }

  return (
    <div className="form">
      <div className="form__title">Schedule (cron)</div>
      <div className="form__grid">
        <Field label="Workflow" hint="The workflow to run on a schedule.">
          <Select value={schedId} ariaLabel="Workflow" onChange={setSchedId} options={wfOptions} />
        </Field>
        <Field label="When (cron)" hint="A 5-field cron expression, or pick a preset below." example="0 9 * * 1">
          <input value={cron} placeholder="0 9 * * 1" onChange={(e) => setCron(e.target.value)} />
        </Field>
        <Field label="Timezone" hint="The timezone the schedule runs in.">
          <Select value={tz} ariaLabel="Timezone" onChange={setTz} options={TZ_OPTIONS} />
        </Field>
      </div>
      <div className="kv">
        <span className="ux-hint">Presets:</span>
        {CRON_PRESETS.map((p) => (
          <button
            key={p.value}
            type="button"
            className="tag tag--accent"
            style={{ cursor: "pointer" }}
            title={p.value}
            onClick={() => setCron(p.value)}
          >
            {p.label}
          </button>
        ))}
      </div>
      {mutation.pending && (
        <PendingHumanCard
          hitlRequestId={mutation.pending.id}
          noun="control"
          verb="control.workflow.schedule"
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
          onClick={schedule}
        >
          {mutation.busy ? "..." : "Schedule"}
        </button>
        {(validationError ?? mutation.error) && (
          <span className="error">{validationError ?? mutation.error}</span>
        )}
      </div>
      {schedResult !== null && <CodeBlock value={schedResult} />}
    </div>
  );
}
