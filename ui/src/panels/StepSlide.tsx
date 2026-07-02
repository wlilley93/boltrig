import { useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import type { InvokeResult } from "../api/types";
import { navigate, useRoute } from "../router";
import { useFetch } from "../useFetch";
import {
  clearWorkflowDraft,
  getWorkflowDraft,
  setWorkflowDraft,
  type WorkflowDraftStep,
} from "./automations/draft";
import { ChipPicker, JsonDisclosure } from "./uxForm";
import { ArmConfirm, ByChat, PendingHumanCard, SaveBar } from "./uxFlow";
import {
  CONSEQUENCE,
  EmptyState,
  FetchError,
  Field,
  InfoCallout,
  PageIntro,
  StatusBadge,
} from "./ux";
import { apiReason, prettyJson } from "./shared";

type WorkflowStep = WorkflowDraftStep;

interface SaveParams extends Record<string, unknown> {
  id: string;
  version: string;
  source: string;
  definition: Record<string, unknown>;
  intent_tags: string[];
}

function extractSteps(value: unknown): WorkflowStep[] {
  if (!value || typeof value !== "object") return [];
  const steps = (value as { steps?: unknown }).steps;
  if (!Array.isArray(steps)) return [];
  const parsed: Array<WorkflowStep | null> = steps.map((raw) => {
      if (!raw || typeof raw !== "object") return null;
      const r = raw as Record<string, unknown>;
      if (typeof r.id !== "string") return null;
      return {
        id: r.id,
        parents: Array.isArray(r.parents)
          ? r.parents.filter((p): p is string => typeof p === "string")
          : [],
        action: typeof r.action === "string" ? r.action : "",
        params:
          r.params && typeof r.params === "object" && !Array.isArray(r.params)
            ? (r.params as Record<string, unknown>)
            : undefined,
        description: typeof r.description === "string" ? r.description : undefined,
      };
    });
  return parsed.filter((s): s is WorkflowStep => s !== null);
}

function bumpPatch(version: string): string {
  const parts = version.split(".");
  const patch = Number(parts[2] ?? "0");
  if (parts.length >= 3 && Number.isFinite(patch)) {
    return `${parts[0]}.${parts[1]}.${patch + 1}`;
  }
  return `${version}.1`;
}

function uniqueStepId(steps: WorkflowStep[], base: string): string {
  const safe = (base || "step").replace(/[^a-zA-Z0-9_-]/g, "_") || "step";
  const taken = new Set(steps.map((s) => s.id));
  let id = safe;
  let i = 1;
  while (taken.has(id)) {
    i += 1;
    id = `${safe}_${i}`;
  }
  return id;
}

function wouldCreateCycle(steps: WorkflowStep[], stepId: string, parentId: string): boolean {
  const byParent = new Map<string, string[]>();
  for (const step of steps) {
    for (const parent of step.parents) {
      const list = byParent.get(parent) ?? [];
      list.push(step.id);
      byParent.set(parent, list);
    }
  }
  const queue = [...(byParent.get(stepId) ?? [])];
  const seen = new Set<string>();
  while (queue.length > 0) {
    const id = queue.shift() as string;
    if (id === parentId) return true;
    if (seen.has(id)) continue;
    seen.add(id);
    queue.push(...(byParent.get(id) ?? []));
  }
  return false;
}

function classifyResult(result: InvokeResult): string | null {
  if (result.status === "denied" || result.status === "error") return result.reason;
  return null;
}

export function StepSlide({ stepKey }: { stepKey?: string }) {
  const route = useRoute();
  const wfid = route.segs[1];
  const stepId = stepKey ?? route.segs[3];
  const detail = useFetch(
    () => (wfid ? api.getWorkflow(wfid) : Promise.reject(new Error("No workflow selected"))),
    [wfid],
  );
  const caps = useFetch(() => api.capabilities(), []);
  const [steps, setSteps] = useState<WorkflowStep[]>([]);
  const [paramsText, setParamsText] = useState("{}");
  const [paramsError, setParamsError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<{ id: string; params: SaveParams } | null>(null);
  const [savedKey, setSavedKey] = useState("");

  useEffect(() => {
    if (!detail.data || !wfid) return;
    const saved = extractSteps(detail.data.definition);
    const next = getWorkflowDraft(wfid) ?? saved;
    setSteps(next);
    setSavedKey(JSON.stringify(saved));
    const current = next.find((step) => step.id === stepId);
    setParamsText(prettyJson(current?.params ?? {}));
    setParamsError(null);
    setError(null);
    setPending(null);
  }, [detail.data, stepId, wfid]);

  const verbs = caps.data?.verbs ?? [];
  const verbById = useMemo(() => new Map(verbs.map((v) => [v.id, v])), [verbs]);
  const step = steps.find((s) => s.id === stepId);
  const currentVerb = step ? verbById.get(step.action) : undefined;
  const actionUnavailable = !!step?.action && !currentVerb;
  const dirty = JSON.stringify(steps) !== savedKey;

  function commitSteps(next: WorkflowStep[]) {
    setSteps(next);
    if (wfid) setWorkflowDraft(wfid, next);
  }

  function replaceStep(next: WorkflowStep) {
    commitSteps(steps.map((stepItem) => (stepItem.id === next.id ? next : stepItem)));
  }

  function updateParams(text: string) {
    setParamsText(text);
    try {
      const parsed = JSON.parse(text || "{}");
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        setParamsError("Parameters must be a JSON object.");
        return;
      }
      if (step) replaceStep({ ...step, params: parsed as Record<string, unknown> });
      setParamsError(null);
    } catch {
      setParamsError("Fix the JSON before requesting a change.");
    }
  }

  function changeAction(action: string) {
    if (!step) return;
    replaceStep({ ...step, action, params: {} });
    setParamsText("{}");
    setParamsError(null);
  }

  function appendAfter() {
    if (!step) return;
    const id = uniqueStepId(steps, `${step.id}_next`);
    commitSteps([...steps, { id, parents: [step.id], action: "", params: {} }]);
    navigate(`/automations/${encodeURIComponent(wfid)}/step/${encodeURIComponent(id)}`);
  }

  function insertBefore() {
    if (!step) return;
    const id = uniqueStepId(steps, `${step.id}_before`);
    const inserted: WorkflowStep = {
      id,
      parents: [...step.parents],
      action: "",
      params: {},
    };
    commitSteps([
      ...steps.map((item) =>
        item.id === step.id ? { ...item, parents: [id] } : item,
      ),
      inserted,
    ]);
    navigate(`/automations/${encodeURIComponent(wfid)}/step/${encodeURIComponent(id)}`);
  }

  async function deleteStep() {
    if (!step) return;
    const remaining = steps
      .filter((item) => item.id !== step.id)
      .map((item) => ({
        ...item,
        parents: item.parents.filter((parent) => parent !== step.id),
      }));
    commitSteps(remaining);
    navigate(`/automations/${encodeURIComponent(wfid)}`);
  }

  function saveParams(): SaveParams | null {
    if (!detail.data) return null;
    if (paramsError) return null;
    return {
      id: detail.data.id,
      version: bumpPatch(detail.data.version),
      source: detail.data.source,
      definition: { ...detail.data.definition, steps },
      intent_tags: detail.data.intent_tags,
    };
  }

  async function save() {
    const params = saveParams();
    if (!params) {
      setError(paramsError ?? "Workflow detail is not loaded.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const result = await api.invoke({
        noun: "control",
        verb: "control.workflow.upsert",
        params,
      });
      if (result.status === "pending_human") {
        setPending({ id: result.hitl_request_id, params });
        return;
      }
      const reason = classifyResult(result);
      if (reason) {
        setError(reason);
        return;
      }
      setSavedKey(JSON.stringify(steps));
    } catch (err) {
      setError(apiReason(err));
    } finally {
      setSaving(false);
    }
  }

  if (!wfid || !stepId) {
    return (
      <section className="panel au-step">
        <EmptyState title="No step selected" body="Open a workflow step from the automations row." />
      </section>
    );
  }
  if (detail.loading && !detail.data) {
    return <section className="panel au-step"><p className="muted">Loading step...</p></section>;
  }
  if (!step) {
    return (
      <section className="panel au-step">
        <FetchError error={detail.error} status={detail.errorStatus} onRetry={detail.reload} />
        <EmptyState
          title="Step not found"
          body={`No step named ${stepId} is present in ${wfid}.`}
          action={<button className="btn" onClick={() => navigate(`/automations/${encodeURIComponent(wfid)}`)}>Back to canvas</button>}
        />
      </section>
    );
  }

  const parentOptions = steps
    .filter((candidate) => candidate.id !== step.id)
    .map((candidate) => {
      const cycle = wouldCreateCycle(steps, step.id, candidate.id);
      return {
        value: candidate.id,
        label: candidate.id,
        disabled: cycle,
        disabledReason: cycle ? "Would create a cycle" : undefined,
      };
    });

  return (
    <section className="panel au-step">
      <PageIntro
        title={<><code>{step.id}</code> <span className="badge">step</span></>}
        lead={`Editing ${wfid}. Step changes save the whole workflow definition through the governed control plane.`}
        how="The workflow still runs the last saved version until the save request is approved and applied."
        actions={
          <>
            <ByChat phrase={`Explain and improve step ${step.id} in workflow ${wfid}.`} />
            <button className="btn" onClick={() => navigate(`/automations/${encodeURIComponent(wfid)}`)}>
              Back to canvas
            </button>
          </>
        }
      />

      <FetchError error={caps.error} status={caps.errorStatus} onRetry={caps.reload} />

      <div className="au-step__toolbar">
        <button type="button" className="btn" onClick={insertBefore}>
          Insert before
        </button>
        <button type="button" className="btn" onClick={appendAfter}>
          Append after
        </button>
        <ArmConfirm
          label="Delete step"
          armLabel={<>Delete <code>{step.id}</code>? Downstream steps keep their other parents.</>}
          confirmLabel="Delete"
          busyLabel="Deleting"
          tone="danger"
          onConfirm={deleteStep}
        />
      </div>

      <div className="au-step__grid">
        <section className="au-step__card">
          <h3>Action</h3>
          <Field
            label="Verb"
            hint="Choose the governed verb this step runs. High-consequence verbs pause at runtime."
            required
          >
            <select
              value={step.action}
              aria-label="Step verb"
              onChange={(e) => changeAction(e.target.value)}
            >
              <option value="">Choose a verb</option>
              {actionUnavailable && (
                <option value={step.action}>{step.action} (not available to this identity)</option>
              )}
              {verbs.map((verb) => (
                <option key={verb.id} value={verb.id}>
                  {verb.id}
                </option>
              ))}
            </select>
          </Field>
          {currentVerb && (
            <div className="au-step__verbfacts">
              <StatusBadge value={currentVerb.consequence} glossary={CONSEQUENCE} />
              <span className="badge">{currentVerb.binding?.target_type ?? "kernel"}</span>
              {currentVerb.binding?.target_ref && <code>{currentVerb.binding.target_ref}</code>}
            </div>
          )}
          {currentVerb?.consequence === "high" && (
            <InfoCallout tone="consequence">
              This step is high consequence. Runs pause here for human approval
              before it executes.
            </InfoCallout>
          )}
          {actionUnavailable && (
            <InfoCallout tone="warn">
              This saved action is not in the current capability list. You can
              keep it as-is or choose a replacement verb.
            </InfoCallout>
          )}
        </section>

        <section className="au-step__card">
          <h3>Parameters</h3>
          <JsonDisclosure
            value={paramsText}
            onChange={updateParams}
            error={paramsError}
            summaryNote="Step params"
            defaultOpen
          />
        </section>

        <section className="au-step__card">
          <h3>Runs after</h3>
          <Field
            label="Parent steps"
            hint="This step runs only after every selected parent has completed."
          >
            <ChipPicker
              value={step.parents}
              onChange={(parents) => replaceStep({ ...step, parents })}
              options={parentOptions}
              mono
              ariaLabel="Parent steps"
              emptyHint="No parents. This is a root step."
            />
          </Field>
        </section>

        <section className="au-step__card">
          <h3>Description</h3>
          <textarea
            value={step.description ?? ""}
            rows={6}
            placeholder="Describe what this step does"
            onChange={(e) =>
              replaceStep({ ...step, description: e.target.value || undefined })
            }
          />
        </section>
      </div>

      {error && <InfoCallout tone="warn">{error}</InfoCallout>}
      {pending && (
        <PendingHumanCard
          hitlRequestId={pending.id}
          noun="control"
          verb="control.workflow.upsert"
      sentParams={pending.params}
      onApplied={(result) => {
        const reason = classifyResult(result);
        if (reason) {
          setError(reason);
          return;
        }
        const savedSteps = extractSteps(pending.params.definition);
        setSavedKey(JSON.stringify(savedSteps));
        setPending(null);
      }}
          onDenied={(reason) => setError(reason)}
        />
      )}
      <SaveBar
        dirty={dirty}
        saving={saving}
        label={<>Unsaved changes to <code>{wfid}</code></>}
        saveLabel="Save workflow"
        governed
        onSave={() => void save()}
        onDiscard={() => {
          if (!detail.data) return;
          const restored = extractSteps(detail.data.definition);
          setSteps(restored);
          clearWorkflowDraft(wfid);
          setSavedKey(JSON.stringify(restored));
          const restoredStep = restored.find((item) => item.id === step.id);
          setParamsText(prettyJson(restoredStep?.params ?? {}));
          setParamsError(null);
          setError(null);
        }}
      />
    </section>
  );
}
