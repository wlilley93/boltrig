import { useState } from "react";

import { api } from "../../api/client";
import type {
  CapabilitiesResponse,
  VerbInfo,
  WorkflowRunDescriptor,
  WorkflowRunRecord,
  WorkflowSummary,
  WorkflowsResponse,
} from "../../api/types";
import { useFetch, type FetchState } from "../../useFetch";
import {
  CodeBlock,
  RunLink,
  errText,
  listToCsv,
  parseJson,
  runBadgeClass,
  stepBadgeClass,
} from "../shared";
import { Field, Select } from "../ux";
import { WorkflowCanvas } from "../WorkflowCanvas";
import { UpsertWorkflowForm } from "./workflow/forms/UpsertWorkflowForm";

// View toggle inside the Workflow Studio: the existing form flow or the new
// React Flow canvas. Both round-trip the same definition.steps shape.
type WorkflowView = "form" | "canvas";

// A ready-made {value,label} for the shared Select. The four action forms all
// pick from the same list of workflow ids, so the parent computes it once.
type WorkflowOption = { value: string; label: string };

const TZ_OPTIONS = [
  "UTC",
  "Europe/London",
  "Europe/Paris",
  "America/New_York",
  "America/Chicago",
  "America/Los_Angeles",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Sydney",
].map((z) => ({ value: z, label: z }));

const CRON_PRESETS: ReadonlyArray<{ label: string; value: string }> = [
  { label: "Hourly", value: "0 * * * *" },
  { label: "Daily 9am", value: "0 9 * * *" },
  { label: "Weekdays 9am", value: "0 9 * * 1-5" },
  { label: "Mondays 9am", value: "0 9 * * 1" },
];

function ScheduleForm({ wfOptions }: { wfOptions: WorkflowOption[] }) {
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

function TriggerForm({ wfOptions }: { wfOptions: WorkflowOption[] }) {
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

function ExecuteForm({ wfOptions }: { wfOptions: WorkflowOption[] }) {
  const [execId, setExecId] = useState("");
  const [execInputs, setExecInputs] = useState("{}");
  const [execBusy, setExecBusy] = useState(false);
  const [execError, setExecError] = useState<string | null>(null);
  const [execResult, setExecResult] = useState<WorkflowRunRecord | null>(null);

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
    setExecBusy(true);
    setExecError(null);
    setExecResult(null);
    try {
      const res = await api.executeWorkflow(execId.trim(), parsedInputs);
      setExecResult(res);
    } catch (err) {
      setExecError(errText(err));
    } finally {
      setExecBusy(false);
    }
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
      <div className="form__actions">
        <button
          className="btn btn--primary"
          disabled={execBusy}
          onClick={execute}
        >
          {execBusy ? "..." : "Execute"}
        </button>
        {execError && <span className="error">{execError}</span>}
      </div>
      {execResult && (
        <div className="stack">
          <div className="kv">
            <span className={`badge ${runBadgeClass(execResult.status)}`}>
              {execResult.status}
            </span>
            <RunLink runId={execResult.run_id} />
            <span className="muted">
              {execResult.workflow_id} v{execResult.version}
            </span>
          </div>
          {execResult.steps.length === 0 ? (
            <p className="muted">No steps.</p>
          ) : (
            <ul className="verb-list">
              {execResult.steps.map((s, i) => (
                <li className="verb-row" key={`${s.id}-${i}`}>
                  <div className="verb-row__main">
                    <code className="verb-row__id">{s.id}</code>
                    {s.action && (
                      <span className="muted">{s.action}</span>
                    )}
                    <span className={`badge ${stepBadgeClass(s.status)}`}>
                      {s.status}
                    </span>
                  </div>
                  {s.reason && (
                    <div className="verb-row__meta">
                      <span className="muted">reason: {s.reason}</span>
                    </div>
                  )}
                  {s.output !== undefined && (
                    <CodeBlock value={s.output} />
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function RunsForm({ wfOptions }: { wfOptions: WorkflowOption[] }) {
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
          {runs.map((r) => (
            <RunLink runId={r} key={r} />
          ))}
        </p>
      )}
    </div>
  );
}

// The scoped verb registry powers the palette: each id can be pasted as a step
// "action" in the definition JSON.
function VerbPalette({ caps }: { caps: FetchState<CapabilitiesResponse> }) {
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const verbs: VerbInfo[] = caps.data?.verbs ?? [];

  async function copyVerb(verbId: string) {
    try {
      await navigator.clipboard.writeText(verbId);
      setCopiedId(verbId);
    } catch {
      // Clipboard may be unavailable (insecure context); fail quietly.
    }
  }

  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>Verb palette</h3>
        <button className="btn" onClick={() => caps.reload()}>
          Refresh
        </button>
      </div>
      <div className="list-card__body">
        <p className="muted">
          Scoped to this identity. Click a verb to copy its id, then paste it
          as a step <code>action</code> in the definition JSON.
        </p>
        {caps.loading && !caps.data && <p className="muted">Loading...</p>}
        {caps.error && (
          <p className="error">Failed to load: {caps.error}</p>
        )}
        {!caps.loading && !caps.error && verbs.length === 0 && (
          <p className="muted">No verbs visible for this identity.</p>
        )}
        {verbs.map((v) => (
          <button
            className="row-line palette-row"
            key={v.id}
            onClick={() => copyVerb(v.id)}
            title="Copy verb id"
          >
            <div>
              <code>{v.id}</code>{" "}
              {v.consequence && (
                <span className="muted">({v.consequence})</span>
              )}
            </div>
            <div className="kv">
              {v.binding && (
                <span className="badge">{v.binding.target_type}</span>
              )}
              <span className="muted">
                {copiedId === v.id ? "copied" : "copy"}
              </span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

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
