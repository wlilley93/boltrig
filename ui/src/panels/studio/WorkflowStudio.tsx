import { useState } from "react";

import { api } from "../../api/client";
import type {
  CapabilitiesResponse,
  VerbInfo,
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
import { ScheduleForm } from "./workflow/forms/ScheduleForm";
import { TriggerForm } from "./workflow/forms/TriggerForm";
import { UpsertWorkflowForm } from "./workflow/forms/UpsertWorkflowForm";

// View toggle inside the Workflow Studio: the existing form flow or the new
// React Flow canvas. Both round-trip the same definition.steps shape.
type WorkflowView = "form" | "canvas";

// A ready-made {value,label} for the shared Select. The four action forms all
// pick from the same list of workflow ids, so the parent computes it once.
type WorkflowOption = { value: string; label: string };

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
