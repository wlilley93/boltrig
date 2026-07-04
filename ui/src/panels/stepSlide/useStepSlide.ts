import { useEffect, useMemo, useState } from "react";

import { api } from "../../api/client";
import type { InvokeResult, VerbInfo, WorkflowDetail } from "../../api/types";
import { navigate } from "../../router";
import { useFetch, type FetchState } from "../../useFetch";
import {
  clearWorkflowDraft,
  getWorkflowDraft,
  setWorkflowDraft,
} from "../automations/draft";
import { apiReason, prettyJson } from "../shared";
import {
  bumpPatch,
  classifyResult,
  extractSteps,
  uniqueStepId,
  wouldCreateCycle,
  type SaveParams,
  type WorkflowStep,
} from "./stepUtils";

export interface StepSlideState {
  detail: FetchState<WorkflowDetail>;
  capsError: string | null;
  capsErrorStatus: number | null;
  capsReload: () => void;
  steps: WorkflowStep[];
  step: WorkflowStep | undefined;
  verbs: VerbInfo[];
  currentVerb: VerbInfo | undefined;
  actionUnavailable: boolean;
  dirty: boolean;
  parentOptions: {
    value: string;
    label: string;
    disabled?: boolean;
    disabledReason?: string;
  }[];
  paramsText: string;
  paramsError: string | null;
  saving: boolean;
  error: string | null;
  pending: { id: string; params: SaveParams } | null;
  updateParams: (text: string) => void;
  changeAction: (action: string) => void;
  replaceStep: (next: WorkflowStep) => void;
  appendAfter: () => void;
  insertBefore: () => void;
  deleteStep: () => Promise<void>;
  save: () => Promise<void>;
  discard: () => void;
  onApplied: (result: InvokeResult) => void;
  onDenied: (reason: string) => void;
}

export function useStepSlide(
  wfid: string | undefined,
  stepId: string | undefined,
): StepSlideState {
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
  const parentOptions = step
    ? steps
        .filter((candidate) => candidate.id !== step.id)
        .map((candidate) => {
          const cycle = wouldCreateCycle(steps, step.id, candidate.id);
          return {
            value: candidate.id,
            label: candidate.id,
            disabled: cycle,
            disabledReason: cycle ? "Would create a cycle" : undefined,
          };
        })
    : [];

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
    if (!step || !wfid) return;
    const id = uniqueStepId(steps, `${step.id}_next`);
    commitSteps([...steps, { id, parents: [step.id], action: "", params: {} }]);
    navigate(`/automations/${encodeURIComponent(wfid)}/step/${encodeURIComponent(id)}`);
  }

  function insertBefore() {
    if (!step || !wfid) return;
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
    if (!step || !wfid) return;
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

  function onApplied(result: InvokeResult) {
    if (!pending) return;
    const reason = classifyResult(result);
    if (reason) {
      setError(reason);
      return;
    }
    const savedSteps = extractSteps(pending.params.definition);
    setSavedKey(JSON.stringify(savedSteps));
    setPending(null);
  }

  function onDenied(reason: string) {
    setError(reason);
  }

  function discard() {
    if (!detail.data || !wfid) return;
    const restored = extractSteps(detail.data.definition);
    setSteps(restored);
    clearWorkflowDraft(wfid);
    setSavedKey(JSON.stringify(restored));
    const restoredStep = restored.find((item) => item.id === stepId);
    setParamsText(prettyJson(restoredStep?.params ?? {}));
    setParamsError(null);
    setError(null);
  }

  return {
    detail,
    capsError: caps.error,
    capsErrorStatus: caps.errorStatus,
    capsReload: caps.reload,
    steps,
    step,
    verbs,
    currentVerb,
    actionUnavailable,
    dirty,
    parentOptions,
    paramsText,
    paramsError,
    saving,
    error,
    pending,
    updateParams,
    changeAction,
    replaceStep,
    appendAfter,
    insertBefore,
    deleteStep,
    save,
    discard,
    onApplied,
    onDenied,
  };
}
