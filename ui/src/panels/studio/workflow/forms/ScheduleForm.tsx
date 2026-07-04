import { useState } from "react";

import { api } from "@/api/client";
import { CodeBlock, errText } from "@/panels/shared";
import { Field, Select } from "@/panels/ux";
import { CRON_PRESETS, TZ_OPTIONS } from "@/panels/studio/workflow/constants";
import type { WfFormProps } from "@/panels/studio/workflow/types";

export function ScheduleForm({ wfOptions }: WfFormProps) {
  const [schedId, setSchedId] = useState("");
  const [cron, setCron] = useState("");
  const [tz, setTz] = useState("UTC");
  const [schedBusy, setSchedBusy] = useState(false);
  const [schedError, setSchedError] = useState<string | null>(null);
  const [schedResult, setSchedResult] = useState<unknown>(null);

  async function schedule() {
    if (!schedId.trim() || !cron.trim()) {
      setSchedError("workflow id and cron are required.");
      return;
    }
    setSchedBusy(true);
    setSchedError(null);
    setSchedResult(null);
    try {
      const res = await api.scheduleWorkflow(schedId.trim(), {
        cron: cron.trim(),
        timezone: tz.trim() || "UTC",
      });
      if (res.status === "ok") setSchedResult(res.schedule);
      else setSchedError(res.reason ?? "schedule rejected");
    } catch (err) {
      setSchedError(errText(err));
    } finally {
      setSchedBusy(false);
    }
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
      <div className="form__actions">
        <button className="btn" disabled={schedBusy} onClick={schedule}>
          {schedBusy ? "..." : "Schedule"}
        </button>
        {schedError && <span className="error">{schedError}</span>}
      </div>
      {schedResult !== null && <CodeBlock value={schedResult} />}
    </div>
  );
}
