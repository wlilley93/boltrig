import {
  type KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  BoltrigApiError,
  type ChannelSummary,
  type CreateWorkflowTriggerRequest,
  type ScheduleWorkflowRequest,
  type ScheduleWorkflowResponse,
  type StatusAck,
  type TriggerWorkflowRequest,
  type UpsertWorkflowRequest,
  type VerbInfo,
  type WorkflowLifecycleResponse,
  type WorkflowRunDescriptor,
  type WorkflowRunRecord,
  type WorkflowRunStat,
  type WorkflowScheduleOccurrence,
  type WorkflowScheduleState,
  type WorkflowStepDefinition,
  type WorkflowStepResult,
  type WorkflowSummary,
  type WorkflowTriggerDelivery,
  type WorkflowTriggerMutationResponse,
  type WorkflowTriggerSource,
  type WorkflowTriggerSummary,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import { useRouteSelection } from "../useRouteSelection";
import {
  blankWorkflowDraft,
  buildWorkflowRequest,
  isPreservedUnsupportedStep,
  loopBodyStepIds,
  nextStepId,
  validateWorkflowDraft,
  workflowActionLimitation,
  workflowDetailToDraft,
  WORKER_CONTROL_ACTIONS,
  type WorkflowDraft,
  type WorkflowStepDraft,
} from "../workflowDraft";
import {
  ExactApprovalFinalizer,
  governedResultReason,
  governedRouteRefusal,
  type GovernedResult,
  useExactApprovalFinalizer,
} from "./ExactApprovalFinalizer";
import {
  checkDefinitionSteps,
  checkDraftSteps,
  type GraphProblem,
} from "./routine/graphChecks";
import {
  coerceSampleText,
  predicateSampleRefs,
  selectBranchLabel,
} from "./routine/predicates";
import {
  RoutineCanvas,
  type CanvasEdgeRef,
  type CanvasMode,
  type TryWalkState,
} from "./routine/RoutineCanvas";
import { RecentlyChanged } from "./build/RecentlyChanged";
import { StepInspector } from "./routine/StepInspector";
import { RoutineThumb } from "./RoutineThumb";
import { Unavailable } from "./Shell";

import "./AutomationViewParity.css";

type PendingTriggerMutation =
  | {
      kind: "create";
      requestId: string;
      name: string;
      source: "webhook";
      state: PendingTriggerState;
    }
  | {
      kind: "rotate";
      requestId: string;
      trigger: WorkflowTriggerSummary;
      state: PendingTriggerState;
    };
type PendingTriggerState = "waiting" | "checking" | "ready" | "unavailable";

function samePendingTrigger(
  left: PendingTriggerMutation | null,
  right: PendingTriggerMutation,
): boolean {
  if (!left || left.kind !== right.kind || left.requestId !== right.requestId) {
    return false;
  }
  if (left.kind === "create" && right.kind === "create") {
    return left.name === right.name && left.source === right.source;
  }
  return left.kind === "rotate" && right.kind === "rotate"
    && left.trigger.id === right.trigger.id;
}

function pendingTriggerWithState(
  current: PendingTriggerMutation | null,
  expected: PendingTriggerMutation,
  state: PendingTriggerState,
): PendingTriggerMutation | null {
  if (!samePendingTrigger(current, expected) || !current) return current;
  return current.kind === "create"
    ? { ...current, state }
    : { ...current, state };
}
type AutomationState = "loading" | "ready" | "denied" | "unavailable";
type OccurrenceFinalizationState =
  | "waiting"
  | "checking"
  | "invalidated"
  | "rejected"
  | "expired"
  | "consumed"
  | "unavailable"
  | null;

interface PendingOccurrenceRetry {
  workflowId: string;
  scheduledFor: string;
  runId: string;
  approvalId: string;
  invalidated: boolean;
}

type ExactAutomationMutation =
  | { kind: "save"; body: UpsertWorkflowRequest }
  | {
      kind: "schedule";
      workflowId: string;
      body: ScheduleWorkflowRequest;
    }
  | {
      kind: "lifecycle";
      workflowId: string;
      action: "unschedule" | "archive" | "restore";
    }
  | {
      kind: "queue";
      workflowId: string;
      body: TriggerWorkflowRequest;
    }
  | {
      kind: "execute";
      workflowId: string;
      inputs: Record<string, unknown>;
    }
  | {
      kind: "bind_channel";
      workflowId: string;
      body: CreateWorkflowTriggerRequest & { source: "channel" };
    }
  | {
      kind: "trigger_lifecycle";
      workflowId: string;
      triggerId: string;
      action: "enable" | "disable";
    };

interface ExactAutomationResult extends GovernedResult {
  value?:
    | StatusAck
    | ScheduleWorkflowResponse
    | WorkflowLifecycleResponse
    | WorkflowRunDescriptor
    | WorkflowRunRecord
    | WorkflowTriggerMutationResponse;
}

export function AutomationsView() {
  const [selectedWorkflowId, setSelectedWorkflowId] = useRouteSelection("automations");
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([]);
  const [verbs, setVerbs] = useState<VerbInfo[]>([]);
  const [surfaceState, setSurfaceState] = useState<AutomationState>("loading");
  const loadedWorkflows = useRef(false);
  const selectedWorkflowIdRef = useRef(selectedWorkflowId);
  const workflowLoadSequence = useRef(0);
  const [draft, setDraft] = useState<WorkflowDraft | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [cron, setCron] = useState("0 9 * * 1-5");
  const [timezone, setTimezone] = useState("UTC");
  const [stats, setStats] = useState<Record<string, WorkflowRunStat>>({});
  const [runIds, setRunIds] = useState<string[]>([]);
  const [lastExecution, setLastExecution] = useState<WorkflowRunRecord | null>(null);
  const [workflowStatus, setWorkflowStatus] = useState<"active" | "archived">("active");
  const [hasSchedule, setHasSchedule] = useState(false);
  const [scheduleState, setScheduleState] = useState<WorkflowScheduleState | null>(null);
  const [scheduleOccurrences, setScheduleOccurrences] = useState<WorkflowScheduleOccurrence[]>([]);
  const [scheduleHistoryTruncated, setScheduleHistoryTruncated] = useState(false);
  const [pendingOccurrenceRetry, setPendingOccurrenceRetry] =
    useState<PendingOccurrenceRetry | null>(null);
  const [occurrenceFinalization, setOccurrenceFinalization] =
    useState<OccurrenceFinalizationState>(null);
  const [triggers, setTriggers] = useState<WorkflowTriggerSummary[]>([]);
  const [channels, setChannels] = useState<ChannelSummary[]>([]);
  const [triggerDeliveries, setTriggerDeliveries] = useState<WorkflowTriggerDelivery[]>([]);
  const [triggerSecret, setTriggerSecret] = useState<{
    secret: string;
    webhookPath?: string;
  } | null>(null);
  const [pendingTrigger, setPendingTrigger] = useState<PendingTriggerMutation | null>(null);
  const pendingTriggerRef = useRef<PendingTriggerMutation | null>(pendingTrigger);
  const triggerDeliveryLoadSequence = useRef(0);
  const [listNotice, setListNotice] = useState("");
  const [detailError, setDetailError] = useState("");
  const [discardDialogOpen, setDiscardDialogOpen] = useState(false);
  // A picker card with a problem opens the editor with that step selected, so
  // the State word and the canvas agree about what to fix first.
  const [focusStepId, setFocusStepId] = useState<string | null>(null);
  const exactApprovalInvalidator = useRef<() => void>(() => undefined);
  const discardDialogRef = useRef<HTMLElement>(null);
  const discardCancelRef = useRef<HTMLButtonElement>(null);
  const discardConfirmRef = useRef<HTMLButtonElement>(null);
  const discardOpenerRef = useRef<HTMLElement | null>(null);
  selectedWorkflowIdRef.current = selectedWorkflowId;
  pendingTriggerRef.current = pendingTrigger;

  useEffect(() => {
    if (!discardDialogOpen) return;
    discardCancelRef.current?.focus();
    const opener = discardOpenerRef.current;
    return () => {
      if (opener?.isConnected) opener.focus();
      discardOpenerRef.current = null;
    };
  }, [discardDialogOpen]);

  const invalidatePendingOccurrenceRetry = useCallback(() => {
    setPendingOccurrenceRetry((current) => (
      current === null ? null : { ...current, invalidated: true }
    ));
    setOccurrenceFinalization((current) => (
      current === "waiting" || current === "checking"
        ? "invalidated"
        : current
    ));
  }, []);

  const invalidateExactApproval = useCallback(() => {
    exactApprovalInvalidator.current();
  }, []);

  const refreshList = useCallback(async () => {
    invalidateExactApproval();
    invalidatePendingOccurrenceRetry();
    setListNotice("");
    try {
      const result = await client.workflows();
      setWorkflows(result.workflows);
      loadedWorkflows.current = true;
      setSurfaceState("ready");
    } catch (reason) {
      const denied = reason instanceof BoltrigApiError
        && [401, 403].includes(reason.status);
      if (!denied && loadedWorkflows.current) {
        setListNotice("Workflow library refresh failed. Showing the last loaded definitions.");
      } else {
        loadedWorkflows.current = false;
        workflowLoadSequence.current += 1;
        triggerDeliveryLoadSequence.current += 1;
        setWorkflows([]);
        setDraft(null);
        setTriggerDeliveries([]);
        setSurfaceState(denied ? "denied" : "unavailable");
      }
    }
    try {
      const result = await client.capabilities();
      setVerbs([...result.verbs].sort((left, right) => left.id.localeCompare(right.id)));
    } catch {
      setVerbs([]);
    }
    try {
      const result = await client.workflowStats();
      setStats(Object.fromEntries(result.stats.map((item) => [item.workflow_id, item])));
    } catch {
      setStats({});
    }
  }, [invalidateExactApproval, invalidatePendingOccurrenceRetry]);

  useEffect(() => {
    void refreshList();
  }, [refreshList]);

  const openWorkflow = useCallback(async (id: string) => {
    invalidateExactApproval();
    invalidatePendingOccurrenceRetry();
    const sequence = ++workflowLoadSequence.current;
    triggerDeliveryLoadSequence.current += 1;
    setBusy(true);
    setMessage("");
    setDetailError("");
    setDraft(null);
    setTriggerDeliveries([]);
    try {
      const [
        detail,
        runs,
        triggerResult,
        channelResult,
        finalizationResult,
        occurrenceResult,
      ] = await Promise.all([
        client.workflow(id),
        client.workflowRuns(id).catch(() => ({ workflow_id: id, runs: [] })),
        client.workflowTriggers(id).catch(() => ({ workflow_id: id, triggers: [] })),
        client.channels().catch(() => ({ channels: [] })),
        client.workflowTriggerFinalizations(id).catch(() => ({
          workflow_id: id,
          finalizations: [],
        })),
        client.workflowScheduleOccurrences(id).catch(() => ({
          workflow_id: id,
          occurrences: [],
          truncated: false,
          backfill: {
            status: "unavailable" as const,
            reason: "historical_backfill_not_supported_by_canonical_claim" as const,
          },
        })),
      ]);
      if (
        workflowLoadSequence.current !== sequence
        || selectedWorkflowIdRef.current !== id
      ) return;
      setDraft(workflowDetailToDraft(detail));
      setRunIds(runs.runs);
      setTriggers(triggerResult.triggers);
      setChannels(channelResult.channels ?? []);
      setTriggerDeliveries([]);
      setTriggerSecret(null);
      const finalization = [...finalizationResult.finalizations].sort(
        (left, right) => Number(right.state === "ready") - Number(left.state === "ready"),
      )[0];
      if (finalization?.action === "create") {
        setPendingTrigger({
          kind: "create",
          requestId: finalization.request_id,
          name: finalization.name,
          source: "webhook",
          state: finalization.state,
        });
      } else if (finalization?.action === "rotate") {
        const target = triggerResult.triggers.find(
          (trigger) => trigger.id === finalization.trigger_id,
        );
        setPendingTrigger(target ? {
          kind: "rotate",
          requestId: finalization.request_id,
          trigger: target,
          state: finalization.state,
        } : null);
      } else {
        setPendingTrigger(null);
      }
      setLastExecution(null);
      setDirty(false);
      setWorkflowStatus(detail.status ?? "active");
      const schedule = detail.schedule ?? scheduleOf(detail.definition);
      setHasSchedule(Boolean(schedule));
      setScheduleState(detail.schedule_state ?? null);
      setScheduleOccurrences(occurrenceResult.occurrences);
      setScheduleHistoryTruncated(occurrenceResult.truncated);
      setCron(schedule?.cron ?? "0 9 * * 1-5");
      setTimezone(schedule?.timezone ?? "UTC");
    } catch {
      if (
        workflowLoadSequence.current === sequence
        && selectedWorkflowIdRef.current === id
      ) setDetailError("This workflow is unavailable in the active workspace.");
    } finally {
      if (
        workflowLoadSequence.current === sequence
        && selectedWorkflowIdRef.current === id
      ) setBusy(false);
    }
  }, [invalidateExactApproval, invalidatePendingOccurrenceRetry]);

  useEffect(() => {
    if (!selectedWorkflowId || surfaceState !== "ready") {
      workflowLoadSequence.current += 1;
      if (surfaceState !== "ready") setDraft(null);
      return;
    }
    void openWorkflow(selectedWorkflowId);
    return () => {
      workflowLoadSequence.current += 1;
    };
  }, [openWorkflow, selectedWorkflowId, surfaceState]);

  const exactApproval = useExactApprovalFinalizer<
    ExactAutomationMutation,
    ExactAutomationResult
  >({
    isCurrent: (input) => {
      if (!draft) return false;
      if (input.kind === "save") {
        if (
          selectedWorkflowIdRef.current !== null
          && selectedWorkflowIdRef.current !== input.body.id
        ) return false;
        try {
          return routeInputEquals(input.body, buildWorkflowRequest(draft));
        } catch {
          return false;
        }
      }
      if (
        draft.id !== input.workflowId
        || selectedWorkflowIdRef.current !== input.workflowId
        || dirty
      ) return false;
      if (input.kind === "schedule") {
        return workflowStatus === "active"
          && routeInputEquals(input.body, { cron, timezone });
      }
      if (input.kind === "lifecycle") {
        if (input.action === "unschedule") {
          return workflowStatus === "active" && hasSchedule;
        }
        return input.action === "archive"
          ? workflowStatus === "active"
          : workflowStatus === "archived";
      }
      if (input.kind === "queue" || input.kind === "execute") {
        return workflowStatus === "active";
      }
      if (input.kind === "bind_channel") {
        return workflowStatus === "active"
          && channels.some((channel) => (
            channel.id === input.body.channel_id && channel.enabled
          ));
      }
      const trigger = triggers.find((item) => item.id === input.triggerId);
      return workflowStatus === "active"
        && trigger !== undefined
        && trigger.enabled === (input.action === "disable");
    },
    replay: async (input, approvalId) => {
      if (input.kind === "save") {
        return normalizeExactResult(
          await client.upsertWorkflow(input.body, approvalId),
        );
      }
      if (input.kind === "schedule") {
        return normalizeExactResult(
          await client.scheduleWorkflow(
            input.workflowId, input.body, approvalId,
          ),
        );
      }
      if (input.kind === "lifecycle") {
        const result = input.action === "unschedule"
          ? await client.unscheduleWorkflow(input.workflowId, approvalId)
          : input.action === "archive"
            ? await client.archiveWorkflow(input.workflowId, approvalId)
            : await client.restoreWorkflow(input.workflowId, approvalId);
        return normalizeExactResult(result);
      }
      if (input.kind === "queue") {
        const result = await client.triggerWorkflow(
          input.workflowId, input.body, approvalId,
        );
        if (isPendingHuman(result)) return result;
        const refusal = governedRouteRefusal(result);
        if (refusal) {
          return { status: refusal.status, reason: refusal.reason, value: result };
        }
        if (result.error) {
          return { status: "error", reason: result.error, value: result };
        }
        return { status: "ok", value: result };
      }
      if (input.kind === "execute") {
        const result = await client.executeWorkflow(
          input.workflowId, input.inputs, approvalId,
        );
        if (isPendingHuman(result)) return result;
        const refusal = governedRouteRefusal(result);
        if (refusal) {
          return { status: refusal.status, reason: refusal.reason, value: result };
        }
        return { status: "ok", value: result };
      }
      if (input.kind === "bind_channel") {
        return normalizeExactResult(
          await client.createWorkflowTrigger(
            input.workflowId, input.body, approvalId,
          ),
        );
      }
      return normalizeExactResult(
        input.action === "enable"
          ? await client.enableWorkflowTrigger(
            input.workflowId, input.triggerId, approvalId,
          )
          : await client.disableWorkflowTrigger(
            input.workflowId, input.triggerId, approvalId,
          ),
      );
    },
    onApplied: async (result, input) => {
      if (input.kind === "save") {
        setDirty(false);
        setSelectedWorkflowId(input.body.id);
        setMessage("Workflow saved through the exact approved authoring route.");
        await refreshList();
        return;
      }
      if (input.kind === "schedule") {
        const value = result.value as ScheduleWorkflowResponse | undefined;
        await openWorkflow(input.workflowId);
        setMessage(scheduleMutationMessage(value));
        return;
      }
      if (input.kind === "lifecycle") {
        await Promise.all([
          openWorkflow(input.workflowId),
          refreshList(),
        ]);
        setMessage(`Workflow ${lifecyclePastTense(input.action)}.`);
        return;
      }
      if (input.kind === "queue") {
        const value = result.value as WorkflowRunDescriptor | undefined;
        setMessage(value?.run_id
          ? `Run ${value.run_id} queued on ${value.engine ?? "the configured executor"}.`
          : "Workflow accepted by the configured executor.");
        await refreshWorkflowRuns(input.workflowId);
        return;
      }
      if (input.kind === "execute") {
        const value = result.value as WorkflowRunRecord | undefined;
        if (value) {
          setLastExecution(value);
          setMessage(`Run ${value.run_id} ${value.status}.`);
        }
        await refreshWorkflowRuns(input.workflowId);
        return;
      }
      await refreshTriggers(input.workflowId);
      setMessage(
        input.kind === "bind_channel"
          ? "Event source bound to this workflow."
          : `Trigger ${input.action === "enable" ? "enabled" : "disabled"}.`,
      );
    },
    onRefused: (result) => {
      setMessage(governedResultReason(
        result, "The exact approved workflow change was refused.",
      ));
    },
  });
  exactApprovalInvalidator.current = exactApproval.invalidate;

  function newWorkflow() {
    invalidateExactApproval();
    invalidatePendingOccurrenceRetry();
    triggerDeliveryLoadSequence.current += 1;
    // An in-flight openWorkflow load can no longer clear busy once the
    // selection moves to the blank draft; settle it here.
    setBusy(false);
    setSelectedWorkflowId(null);
    setDraft(blankWorkflowDraft());
    setRunIds([]);
    setLastExecution(null);
    setTriggers([]);
    setTriggerDeliveries([]);
    setTriggerSecret(null);
    setPendingTrigger(null);
    setDetailError("");
    setDirty(true);
    setWorkflowStatus("active");
    setHasSchedule(false);
    setScheduleState(null);
    setScheduleOccurrences([]);
    setScheduleHistoryTruncated(false);
    setCron("0 9 * * 1-5");
    setTimezone("UTC");
    setMessage("New draft. Saving may pause for author approval.");
  }

  function changeDraft(update: (current: WorkflowDraft) => WorkflowDraft) {
    invalidateExactApproval();
    invalidatePendingOccurrenceRetry();
    setDraft((current) => current ? update(current) : current);
    setDirty(true);
    setMessage("");
  }

  function closeEditor() {
    invalidateExactApproval();
    invalidatePendingOccurrenceRetry();
    workflowLoadSequence.current += 1;
    triggerDeliveryLoadSequence.current += 1;
    setDiscardDialogOpen(false);
    setSelectedWorkflowId(null);
    setDraft(null);
    setTriggerDeliveries([]);
    setDirty(false);
    setFocusStepId(null);
    setBusy(false);
    setMessage("");
  }

  function requestEditorExit() {
    if (!dirty) {
      closeEditor();
      return;
    }
    discardOpenerRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    setDiscardDialogOpen(true);
  }

  function cancelEditorExit() {
    setDiscardDialogOpen(false);
  }

  function handleDiscardDialogKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      cancelEditorExit();
      return;
    }
    if (event.key !== "Tab") return;
    const first = discardCancelRef.current;
    const last = discardConfirmRef.current;
    if (!first || !last) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    } else if (!discardDialogRef.current?.contains(document.activeElement)) {
      event.preventDefault();
      first.focus();
    }
  }

  function updateStep(index: number, patch: Partial<WorkflowStepDraft>) {
    changeDraft((current) => ({
      ...current,
      steps: current.steps.map((step, stepIndex) => (
        stepIndex === index ? { ...step, ...patch } : step
      )),
    }));
  }

  function addStep() {
    changeDraft((current) => ({
      ...current,
      steps: [...current.steps, {
        id: nextStepId(current.steps),
        action: verbs.find((verb) => !workflowActionLimitation(verb.id))?.id ?? "",
        parents: [],
        description: "",
        paramsText: "{}",
        loopBindingsText: "{}",
        branchArm: "",
        parameterField: "params",
        baseRecord: {},
      }],
    }));
  }

  function removeStep(index: number) {
    changeDraft((current) => {
      const removedId = current.steps[index]?.id;
      return {
        ...current,
        steps: current.steps
          .filter((_, stepIndex) => stepIndex !== index)
          .map((step) => ({
            ...step,
            parents: step.parents.filter((parent) => parent !== removedId),
          })),
      };
    });
  }

  async function saveWorkflow() {
    // Re-entry guard: the keyboard path (⌘S in the canvas) is not gated by the
    // Save button's disabled state, and a second governed save racing the
    // first would double-submit.
    if (!draft || busy) return;
    const errors = validateWorkflowDraft(draft);
    if (errors.length) {
      setMessage(errors.join(" "));
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const input: ExactAutomationMutation = {
        kind: "save",
        body: buildWorkflowRequest(draft),
      };
      const result = await client.upsertWorkflow(input.body);
      if (exactApproval.begin(input, result, "Workflow save")) {
        setMessage("Save is waiting for approval in the originating chat.");
      } else if (result.status === "ok") {
        setDirty(false);
        setMessage("Workflow saved.");
        setSelectedWorkflowId(draft.id);
        await refreshList();
      } else {
        setMessage(governedResultReason(
          result, "The workflow was not saved.",
        ));
      }
    } catch {
      setMessage("Workflow authoring is unavailable for this identity.");
    } finally {
      setBusy(false);
    }
  }

  async function scheduleWorkflow() {
    if (!draft || dirty) {
      setMessage("Save the workflow before changing its schedule.");
      return;
    }
    invalidatePendingOccurrenceRetry();
    setBusy(true);
    try {
      const input: ExactAutomationMutation = {
        kind: "schedule",
        workflowId: draft.id,
        body: { cron, timezone },
      };
      const result = await client.scheduleWorkflow(
        input.workflowId, input.body,
      );
      if (exactApproval.begin(input, result, "Workflow schedule change")) {
        setMessage("Schedule change is waiting for approval in the originating chat.");
      } else if (result.status === "ok") {
        await openWorkflow(draft.id);
        setMessage(scheduleMutationMessage(result));
      } else {
        setMessage(result.reason ?? "The schedule was not changed.");
      }
    } catch {
      setMessage("Schedule management is unavailable.");
    } finally {
      setBusy(false);
    }
  }

  async function changeLifecycle(action: "unschedule" | "archive" | "restore") {
    if (!draft || dirty) {
      setMessage("Save the workflow before changing its lifecycle.");
      return;
    }
    invalidatePendingOccurrenceRetry();
    setBusy(true);
    try {
      const input: ExactAutomationMutation = {
        kind: "lifecycle",
        workflowId: draft.id,
        action,
      };
      const result = await (
        action === "unschedule"
          ? client.unscheduleWorkflow(input.workflowId)
          : action === "archive"
            ? client.archiveWorkflow(input.workflowId)
            : client.restoreWorkflow(input.workflowId)
      );
      if (exactApproval.begin(
        input, result, `Workflow ${actionLabel(action).toLowerCase()}`,
      )) {
        setMessage(`${actionLabel(action)} is waiting for approval in the originating chat.`);
      } else if (result.status === "ok") {
        setMessage(`Workflow ${lifecyclePastTense(action)}.`);
        await Promise.all([openWorkflow(draft.id), refreshList()]);
      } else {
        setMessage(result.reason ?? `Workflow ${action} failed.`);
      }
    } catch {
      setMessage("Workflow lifecycle management is unavailable.");
    } finally {
      setBusy(false);
    }
  }

  async function retryScheduleOccurrence(
    occurrence: WorkflowScheduleOccurrence,
  ) {
    if (!draft || dirty || occurrence.status !== "failed") return;
    setBusy(true);
    setMessage("");
    try {
      const result = await client.retryWorkflowScheduleOccurrence(
        draft.id,
        occurrence.scheduled_for,
        occurrence.run_id,
      );
      if (result.status === "pending_human") {
        setPendingOccurrenceRetry({
          workflowId: draft.id,
          scheduledFor: occurrence.scheduled_for,
          runId: occurrence.run_id,
          approvalId: result.hitl_request_id ?? "",
          invalidated: !result.hitl_request_id,
        });
        setOccurrenceFinalization(
          result.hitl_request_id ? "waiting" : "unavailable",
        );
        setMessage("Occurrence retry is waiting for approval in the originating chat.");
      } else if (result.status === "ok") {
        setPendingOccurrenceRetry(null);
        setOccurrenceFinalization(null);
        setMessage(
          `Retry ${result.manual_retries ?? occurrence.retry.manual_retries + 1} queued for the same logical run.`,
        );
        await openWorkflow(draft.id);
      } else {
        setMessage(result.reason ?? "The occurrence was not retried.");
      }
    } catch {
      setMessage(
        "Retry was refused. Only an unchanged terminal failed occurrence under the active schedule can be retried.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function finalizeScheduleOccurrenceRetry() {
    const pending = pendingOccurrenceRetry;
    const current = scheduleOccurrences.find(
      (occurrence) => (
        occurrence.scheduled_for === pending?.scheduledFor
        && occurrence.run_id === pending?.runId
      ),
    );
    if (
      pending === null
      || pending.invalidated
      || draft?.id !== pending.workflowId
      || selectedWorkflowIdRef.current !== pending.workflowId
      || current?.status !== "failed"
    ) {
      setOccurrenceFinalization("invalidated");
      return;
    }
    setBusy(true);
    setOccurrenceFinalization("checking");
    setMessage("");
    try {
      const approval = await client.invokeApprovalState(pending.approvalId);
      if (approval.status === "pending") {
        setOccurrenceFinalization("waiting");
        return;
      }
      if (
        approval.status === "rejected"
        || approval.status === "expired"
        || approval.status === "consumed"
      ) {
        setOccurrenceFinalization(approval.status);
        return;
      }
      const result = await client.retryWorkflowScheduleOccurrence(
        pending.workflowId,
        pending.scheduledFor,
        pending.runId,
        pending.approvalId,
      );
      if (result.status === "ok") {
        setPendingOccurrenceRetry(null);
        setOccurrenceFinalization(null);
        await openWorkflow(pending.workflowId);
        setMessage("The exact approved occurrence was queued for replay.");
      } else if (result.status === "pending_human" && result.hitl_request_id) {
        // The kernel refused the stale fingerprint and issued a fresh exact
        // request. Retain the same occurrence with the new approval handle so
        // the second originating chat decision stays redeemable.
        setPendingOccurrenceRetry({
          ...pending,
          approvalId: result.hitl_request_id,
          invalidated: false,
        });
        setOccurrenceFinalization("waiting");
        setMessage("Occurrence retry is waiting for a fresh approval in the originating chat.");
      } else {
        setOccurrenceFinalization("invalidated");
        setMessage(
          result.reason
            ?? "The approved occurrence snapshot could not be retried.",
        );
      }
    } catch {
      setOccurrenceFinalization("unavailable");
    } finally {
      setBusy(false);
    }
  }

  async function refreshWorkflowRuns(workflowId: string) {
    const [runs, currentStats] = await Promise.all([
      client.workflowRuns(workflowId).catch(() => ({
        workflow_id: workflowId,
        runs: [],
      })),
      client.workflowStats().catch(() => ({ stats: [] })),
    ]);
    setStats(Object.fromEntries(
      currentStats.stats.map((item) => [item.workflow_id, item]),
    ));
    // The selection may have moved while the fetch was in flight; another
    // workflow's runs must not land in this editor.
    if (selectedWorkflowIdRef.current !== workflowId) return;
    setRunIds(runs.runs);
  }

  async function queueWorkflow() {
    if (!draft || dirty) {
      setMessage("Save the workflow before queueing a run.");
      return;
    }
    setBusy(true);
    try {
      const input: ExactAutomationMutation = {
        kind: "queue",
        workflowId: draft.id,
        body: { inputs: {} },
      };
      const result = await client.triggerWorkflow(
        input.workflowId, input.body,
      );
      const refusal = isPendingHuman(result) ? null : governedRouteRefusal(result);
      if (isPendingHuman(result)) {
        exactApproval.begin(input, result, "Workflow queue request");
        setMessage("Run is waiting for approval in the originating chat.");
      } else if (refusal) {
        setMessage(refusal.reason);
      } else if (result.error) {
        setMessage(result.error);
      } else {
        setMessage(result.run_id
          ? `Run ${result.run_id} queued on ${result.engine ?? "the configured executor"}.`
          : "Workflow accepted by the configured executor.");
        await refreshWorkflowRuns(draft.id);
      }
    } catch {
      setMessage("Workflow execution is unavailable on this deployment.");
    } finally {
      setBusy(false);
    }
  }

  async function runWorkflowNow() {
    if (!draft || dirty) {
      setMessage("Save the workflow before running it.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const input: ExactAutomationMutation = {
        kind: "execute",
        workflowId: draft.id,
        inputs: {},
      };
      const result = await client.executeWorkflow(
        input.workflowId, input.inputs,
      );
      if (isPendingHuman(result)) {
        exactApproval.begin(input, result, "Immediate workflow execution");
        setMessage("Execution is waiting for approval in the originating chat.");
      } else {
        const refusal = governedRouteRefusal(result);
        if (refusal) {
          setMessage(refusal.reason);
          return;
        }
        if (selectedWorkflowIdRef.current !== input.workflowId) return;
        setLastExecution(result);
        setMessage(`Run ${result.run_id} ${result.status}.`);
        await refreshWorkflowRuns(draft.id);
      }
    } catch {
      setMessage("Immediate workflow execution is unavailable on this deployment.");
    } finally {
      setBusy(false);
    }
  }

  async function refreshTriggers(workflowId: string) {
    invalidateExactApproval();
    const result = await client.workflowTriggers(workflowId);
    if (selectedWorkflowIdRef.current !== workflowId) return;
    setTriggers(result.triggers);
  }

  async function createTrigger(
    name: string,
    source: WorkflowTriggerSource,
    channelId?: string,
    approvalId?: string,
  ) {
    if (!draft || dirty) {
      setMessage("Save the workflow before binding an event source.");
      return;
    }
    setBusy(true);
    setTriggerSecret(null);
    try {
      const body = {
        name,
        source,
        ...(source === "channel" && channelId ? { channel_id: channelId } : {}),
      };
      const result = approvalId
        ? await client.createWorkflowTrigger(draft.id, body, approvalId)
        : await client.createWorkflowTrigger(draft.id, body);
      if (result.status === "pending_human") {
        if (source === "webhook") {
          const requestId = result.hitl_request_id ?? "";
          setPendingTrigger({
            kind: "create",
            requestId,
            name,
            source,
            state: requestId ? "waiting" : "unavailable",
          });
          setMessage(
            requestId
              ? "Webhook binding is waiting for approval. Check its exact request here after approval to receive the one-time secret."
              : "Webhook binding requires approval, but no request id was returned. Finalization is unavailable and no binding is inferred.",
          );
        } else {
          const input: ExactAutomationMutation = {
            kind: "bind_channel",
            workflowId: draft.id,
            body: {
              name,
              source: "channel",
              ...(channelId ? { channel_id: channelId } : {}),
            },
          };
          exactApproval.begin(input, result, "Channel trigger binding");
          setMessage("Trigger binding is waiting for approval in the originating chat.");
        }
      } else if (result.status === "ok") {
        setPendingTrigger(null);
        if (result.secret) {
          setTriggerSecret({
            secret: result.secret,
            webhookPath: result.webhook_path,
          });
        }
        setMessage("Event source bound to this workflow.");
        await refreshTriggers(draft.id);
      } else {
        setMessage(result.reason ?? "The event source was not bound.");
      }
    } catch {
      setMessage("Workflow trigger management is unavailable.");
    } finally {
      setBusy(false);
    }
  }

  async function changeTrigger(
    trigger: WorkflowTriggerSummary,
    action: "enable" | "disable" | "rotate",
    approvalId?: string,
  ) {
    if (!draft) return;
    setBusy(true);
    setTriggerSecret(null);
    try {
      const result = await (
        action === "enable"
          ? (
              approvalId
                ? client.enableWorkflowTrigger(draft.id, trigger.id, approvalId)
                : client.enableWorkflowTrigger(draft.id, trigger.id)
            )
          : action === "disable"
            ? (
                approvalId
                  ? client.disableWorkflowTrigger(draft.id, trigger.id, approvalId)
                  : client.disableWorkflowTrigger(draft.id, trigger.id)
              )
            : (
                approvalId
                  ? client.rotateWorkflowTriggerSecret(
                      draft.id, trigger.id, approvalId,
                    )
                  : client.rotateWorkflowTriggerSecret(draft.id, trigger.id)
              )
      );
      if (result.status === "pending_human") {
        if (action === "rotate") {
          const requestId = result.hitl_request_id ?? "";
          setPendingTrigger({
            kind: "rotate",
            requestId,
            trigger,
            state: requestId ? "waiting" : "unavailable",
          });
          setMessage(
            requestId
              ? "Secret rotation is waiting for approval. Check its exact request here after approval to receive the new one-time secret."
              : "Secret rotation requires approval, but no request id was returned. Finalization is unavailable and no rotation is inferred.",
          );
        } else {
          exactApproval.begin({
            kind: "trigger_lifecycle",
            workflowId: draft.id,
            triggerId: trigger.id,
            action,
          }, result, `Trigger ${action}`);
          setMessage(`${actionLabel(action)} is waiting for approval in the originating chat.`);
        }
      } else if (result.status === "ok") {
        setPendingTrigger(null);
        if (result.secret) setTriggerSecret({ secret: result.secret });
        setMessage(
          action === "rotate"
            ? "Webhook secret rotated. Replace the old value now."
            : `Trigger ${action === "enable" ? "enabled" : "disabled"}.`,
        );
        await refreshTriggers(draft.id);
      } else {
        setMessage(result.reason ?? `Trigger ${action} failed.`);
      }
    } catch {
      setMessage("Workflow trigger management is unavailable.");
    } finally {
      setBusy(false);
    }
  }

  async function loadTriggerDeliveries(triggerId: string) {
    if (!draft) return;
    const workflowId = draft.id;
    const sequence = ++triggerDeliveryLoadSequence.current;
    setTriggerDeliveries([]);
    try {
      const result = await client.workflowTriggerDeliveries(workflowId, triggerId);
      if (
        triggerDeliveryLoadSequence.current !== sequence
        || selectedWorkflowIdRef.current !== workflowId
        || result.workflow_id !== workflowId
        || result.trigger_id !== triggerId
      ) return;
      setTriggerDeliveries(result.deliveries);
    } catch {
      if (
        triggerDeliveryLoadSequence.current !== sequence
        || selectedWorkflowIdRef.current !== workflowId
      ) return;
      setMessage("Trigger delivery history is unavailable in this workspace.");
    }
  }

  async function refreshTriggerApproval() {
    const pending = pendingTrigger;
    if (!draft || !pending) return;
    const workflowId = draft.id;
    const action = pending.kind === "create" ? "Webhook binding" : "Secret rotation";
    if (!pending.requestId.trim()) {
      setPendingTrigger((current) => (
        pendingTriggerWithState(current, pending, "unavailable")
      ));
      setMessage(
        `${action} approval cannot be checked because no request id was returned. No trigger change is inferred.`,
      );
      return;
    }
    if (dirty || selectedWorkflowIdRef.current !== workflowId) {
      setMessage(
        `${action} approval cannot be checked after the routine selection or draft changed. No trigger change is inferred.`,
      );
      return;
    }

    setPendingTrigger((current) => (
      pendingTriggerWithState(current, pending, "checking")
    ));
    try {
      const result = await client.workflowTriggerFinalizations(workflowId);
      if (
        selectedWorkflowIdRef.current !== workflowId
        || !samePendingTrigger(pendingTriggerRef.current, pending)
      ) return;
      const exact = result.workflow_id === workflowId
        ? result.finalizations.find((finalization) => (
            finalization.request_id === pending.requestId
            && (
              pending.kind === "create"
                ? finalization.action === "create"
                  && finalization.name === pending.name
                  && finalization.source === pending.source
                : finalization.action === "rotate"
                  && finalization.trigger_id === pending.trigger.id
            )
          ))
        : undefined;
      if (exact?.state === "ready") {
        setPendingTrigger((current) => (
          pendingTriggerWithState(current, pending, "ready")
        ));
        setMessage(
          `${action} approval is ready. Finalize the exact request here to receive the one-time secret.`,
        );
      } else if (exact?.state === "waiting") {
        setPendingTrigger((current) => (
          pendingTriggerWithState(current, pending, "waiting")
        ));
        setMessage(`${action} is still waiting for approval in the originating chat.`);
      } else {
        setPendingTrigger((current) => (
          pendingTriggerWithState(current, pending, "unavailable")
        ));
        setMessage(
          `${action} approval is not available for this exact request. No trigger change is inferred.`,
        );
      }
    } catch {
      if (
        selectedWorkflowIdRef.current !== workflowId
        || !samePendingTrigger(pendingTriggerRef.current, pending)
      ) return;
      setPendingTrigger((current) => (
        pendingTriggerWithState(current, pending, "unavailable")
      ));
      setMessage(
        `${action} approval status is unavailable. No trigger change is inferred.`,
      );
    }
  }

  function finalizeTriggerMutation() {
    if (!pendingTrigger) return;
    const action = pendingTrigger.kind === "create"
      ? "Webhook binding"
      : "Secret rotation";
    if (!pendingTrigger.requestId.trim()) {
      setMessage(
        `${action} cannot be finalized because no request id was returned. No trigger change is inferred.`,
      );
      return;
    }
    if (pendingTrigger.state !== "ready") {
      setMessage(
        `${action} cannot be finalized until its exact approval is checked and ready.`,
      );
      return;
    }
    if (pendingTrigger.kind === "create") {
      void createTrigger(
        pendingTrigger.name,
        pendingTrigger.source,
        undefined,
        pendingTrigger.requestId,
      );
      return;
    }
    void changeTrigger(
      pendingTrigger.trigger,
      "rotate",
      pendingTrigger.requestId,
    );
  }

  return (
    <div className={draft ? "page automation-editor-page" : "page"}>
      {/* The console idiom, as on Build and the parity views: one head, one
          title. The Topbar's status line is folded into the lead so the word
          "Routines" is not printed twice down the same column. */}
      <div className={draft ? "automation-editor-viewport" : "console-page"}>
        {!draft && <div className="console-head">
          <div>
            <h1>Routines</h1>
            <p>
              Repeatable work boltrig can run the same way each time. Open a
              routine to see its steps, schedule and latest result.
            </p>
          </div>
          {surfaceState === "ready" && (
            <button className="console-primary" onClick={newWorkflow} type="button">
              <svg aria-hidden fill="none" height="14" stroke="currentColor" strokeLinecap="round" strokeWidth="2" viewBox="0 0 24 24" width="14">
                <line x1="12" x2="12" y1="5" y2="19" /><line x1="5" x2="19" y1="12" y2="12" />
              </svg>
              <span>New routine</span>
            </button>
          )}
        </div>}
        <div
          aria-hidden={draft && discardDialogOpen ? true : undefined}
          className={draft ? "automation-editor-feedback" : "automation-list-feedback"}
          // Boolean(): draft is object-or-null, so `draft && ...` is
          // boolean|null; React 19 types inert as boolean|undefined.
          inert={Boolean(draft && discardDialogOpen)}
        >
          {listNotice && <p className="notice" role="status">{listNotice}</p>}
          {detailError && <p className="notice" role="alert">{detailError}</p>}
          <ExactApprovalFinalizer controller={exactApproval} />
        </div>
        {surfaceState === "loading" && <Unavailable title="Loading automations">Loading workflows.</Unavailable>}
        {surfaceState === "denied" && <Unavailable title="Automation access denied">Your current role cannot view or author workflows.</Unavailable>}
        {surfaceState === "unavailable" && <Unavailable title="Automations unavailable">Workflows could not be reached.</Unavailable>}
        {surfaceState === "ready" && !draft && (
          <RoutinePicker
            onNew={newWorkflow}
            onOpen={(id, focusStep) => {
              invalidateExactApproval();
              setFocusStepId(focusStep ?? null);
              setSelectedWorkflowId(id);
            }}
            stats={stats}
            workflows={workflows}
          />
        )}
        {surfaceState === "ready" && draft && (
          <div
            aria-label="Routine editor viewport"
            aria-hidden={discardDialogOpen ? true : undefined}
            className="automation-editor-stage"
            role="region"
            inert={discardDialogOpen}
          >
            <WorkflowEditor
              draft={draft}
              verbs={verbs}
              dirty={dirty}
              busy={busy}
              message={message}
              cron={cron}
              timezone={timezone}
              runIds={runIds}
              runStat={stats[draft.id]}
              lastExecution={lastExecution}
              status={workflowStatus}
              hasSchedule={hasSchedule}
              scheduleState={scheduleState}
              scheduleOccurrences={scheduleOccurrences}
              scheduleHistoryTruncated={scheduleHistoryTruncated}
              occurrenceFinalization={occurrenceFinalization}
              triggers={triggers}
              channels={channels}
              triggerDeliveries={triggerDeliveries}
              triggerSecret={triggerSecret}
              pendingTrigger={pendingTrigger}
              sessionKey={selectedWorkflowId ?? "new-draft"}
              initialFocusStepId={focusStepId}
              onFocusStepConsumed={() => setFocusStepId(null)}
              onBack={requestEditorExit}
              onDiscard={requestEditorExit}
              onDraft={changeDraft}
              onStep={updateStep}
              onAddStep={addStep}
              onRemoveStep={removeStep}
              onSave={() => void saveWorkflow()}
              onQueue={() => void queueWorkflow()}
              onRunNow={() => void runWorkflowNow()}
              onSchedule={() => void scheduleWorkflow()}
              onUnschedule={() => void changeLifecycle("unschedule")}
              onRetryOccurrence={(occurrence) => (
                void retryScheduleOccurrence(occurrence)
              )}
              onFinalizeOccurrenceRetry={() => (
                void finalizeScheduleOccurrenceRetry()
              )}
              onArchive={() => void changeLifecycle("archive")}
              onRestore={() => void changeLifecycle("restore")}
              onCreateTrigger={(name, source, channelId) => (
                void createTrigger(name, source, channelId)
              )}
              onTriggerAction={(trigger, action) => (
                void changeTrigger(trigger, action)
              )}
              onLoadTriggerDeliveries={(triggerId) => (
                void loadTriggerDeliveries(triggerId)
              )}
              onDismissTriggerSecret={() => setTriggerSecret(null)}
              onFinalizeTrigger={finalizeTriggerMutation}
              onRefreshTriggerApproval={() => void refreshTriggerApproval()}
              onCron={(value) => {
                invalidateExactApproval();
                invalidatePendingOccurrenceRetry();
                setCron(value);
              }}
              onTimezone={(value) => {
                invalidateExactApproval();
                invalidatePendingOccurrenceRetry();
                setTimezone(value);
              }}
              onTriggerDraftChange={invalidateExactApproval}
            />
          </div>
        )}
        {surfaceState === "ready" && draft && discardDialogOpen && (
          <div className="routine-discard-scrim">
            <section
              aria-describedby="routine-discard-description"
              aria-labelledby="routine-discard-title"
              aria-modal="true"
              className="routine-discard-dialog"
              onKeyDown={handleDiscardDialogKeyDown}
              ref={discardDialogRef}
              role="alertdialog"
            >
              <h2 id="routine-discard-title">Discard unsaved changes?</h2>
              <p id="routine-discard-description">
                This routine has changes that have not been saved. Discard them
                and return to Routines?
              </p>
              <div className="routine-discard-actions">
                <button
                  className="secondary-button"
                  onClick={cancelEditorExit}
                  ref={discardCancelRef}
                  type="button"
                >
                  Cancel
                </button>
                <button
                  className="routine-discard-confirm"
                  onClick={closeEditor}
                  ref={discardConfirmRef}
                  type="button"
                >
                  Discard changes
                </button>
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}

interface WorkflowEditorProps {
  draft: WorkflowDraft;
  verbs: VerbInfo[];
  dirty: boolean;
  busy: boolean;
  message: string;
  cron: string;
  timezone: string;
  runIds: string[];
  runStat?: WorkflowRunStat;
  lastExecution: WorkflowRunRecord | null;
  status: "active" | "archived";
  hasSchedule: boolean;
  scheduleState: WorkflowScheduleState | null;
  scheduleOccurrences: WorkflowScheduleOccurrence[];
  scheduleHistoryTruncated: boolean;
  occurrenceFinalization: OccurrenceFinalizationState;
  triggers: WorkflowTriggerSummary[];
  channels: ChannelSummary[];
  triggerDeliveries: WorkflowTriggerDelivery[];
  triggerSecret: { secret: string; webhookPath?: string } | null;
  pendingTrigger: PendingTriggerMutation | null;
  /** Stable identity of the opened selection; resets canvas UI state. */
  sessionKey: string;
  initialFocusStepId: string | null;
  onFocusStepConsumed: () => void;
  onBack: () => void;
  onDiscard: () => void;
  onDraft: (update: (current: WorkflowDraft) => WorkflowDraft) => void;
  onStep: (index: number, patch: Partial<WorkflowStepDraft>) => void;
  onAddStep: () => void;
  onRemoveStep: (index: number) => void;
  onSave: () => void;
  onQueue: () => void;
  onRunNow: () => void;
  onSchedule: () => void;
  onUnschedule: () => void;
  onRetryOccurrence: (occurrence: WorkflowScheduleOccurrence) => void;
  onFinalizeOccurrenceRetry: () => void;
  onArchive: () => void;
  onRestore: () => void;
  onCreateTrigger: (
    name: string,
    source: WorkflowTriggerSource,
    channelId?: string,
  ) => void;
  onTriggerAction: (
    trigger: WorkflowTriggerSummary,
    action: "enable" | "disable" | "rotate",
  ) => void;
  onLoadTriggerDeliveries: (triggerId: string) => void;
  onDismissTriggerSecret: () => void;
  onFinalizeTrigger: () => void;
  onRefreshTriggerApproval: () => void;
  onCron: (value: string) => void;
  onTimezone: (value: string) => void;
  onTriggerDraftChange: () => void;
}

function WorkflowEditor(props: WorkflowEditorProps) {
  const { draft, verbs } = props;
  // Canvas UI state. Keyed by sessionKey (the opened selection), NOT draft.id,
  // so typing in the Workflow id field does not reset the selection.
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<CanvasEdgeRef | null>(null);
  const [mode, setMode] = useState<CanvasMode>("edit");
  const [specOpen, setSpecOpen] = useState(false);
  const [tryValues, setTryValues] = useState<Record<string, string>>({});
  const [zoom, setZoom] = useState(1);
  const [fitRequest, setFitRequest] = useState(0);

  useEffect(() => {
    setSelectedStepId(null);
    setSelectedEdge(null);
    setMode("edit");
    setSpecOpen(false);
    setTryValues({});
    setZoom(1);
    setFitRequest(0);
  }, [props.sessionKey]);

  // A picker card opened through a problem lands with that step selected.
  useEffect(() => {
    if (!props.initialFocusStepId) return;
    setSelectedStepId(props.initialFocusStepId);
    setSelectedEdge(null);
    setMode("edit");
    props.onFocusStepConsumed();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.initialFocusStepId, props.sessionKey]);

  const authoredActions = useMemo(() => [
    ...WORKER_CONTROL_ACTIONS,
    ...verbs
      .map((verb) => verb.id)
      .filter((id) => !workflowActionLimitation(id)),
  ].filter((id, index, all) => all.indexOf(id) === index), [verbs]);
  const actionConsequences = useMemo(
    () => new Map(verbs.map((verb) => [verb.id, verb.consequence ?? "unknown"])),
    [verbs],
  );
  const verbById = useMemo(
    () => new Map(verbs.map((verb) => [verb.id, verb])),
    [verbs],
  );
  const loopBodyIds = useMemo(
    () => new Set(
      draft.steps
        .filter((step) => step.action === "flow.loop")
        .flatMap((step) => loopBodyStepIds(draft.steps, step.id)),
    ),
    [draft.steps],
  );
  // One shared check set drives the Problems strip, the card outlines, and the
  // picker's State word (checkDefinitionSteps over the same rules).
  const problems = useMemo(() => checkDraftSteps(draft.steps), [draft.steps]);

  // Last run paints ONLY from the run record the kernel returned to this
  // screen (POST execute). Loop iteration clones (id__N) fold onto their base
  // card as a derived count; nothing else is aggregated or guessed.
  const runSteps = useMemo(() => {
    if (!props.lastExecution) return null;
    const map = new Map<string, WorkflowStepResult>();
    const cloneCounts = new Map<string, { total: number; failed: number; paused: number }>();
    for (const record of props.lastExecution.steps) {
      const cloneMatch = /^(.+)__[0-9]+$/.exec(record.id);
      if (cloneMatch && draft.steps.some((step) => step.id.trim() === cloneMatch[1])) {
        const tally = cloneCounts.get(cloneMatch[1]) ?? { total: 0, failed: 0, paused: 0 };
        tally.total += 1;
        if (record.status === "failed" || record.status === "error") tally.failed += 1;
        if (record.status === "paused") tally.paused += 1;
        cloneCounts.set(cloneMatch[1], tally);
        continue;
      }
      map.set(record.id, record);
    }
    for (const [base, tally] of cloneCounts) {
      if (map.has(base)) continue;
      map.set(base, {
        id: base,
        status: tally.failed > 0 ? "failed" : tally.paused > 0 ? "paused" : "ok",
        reason: `${tally.total} loop ${tally.total === 1 ? "item" : "items"}${
          tally.failed > 0 ? `, ${tally.failed} failed` : ""
        }`,
      });
    }
    return map;
  }, [props.lastExecution, draft.steps]);

  // Try it: the same fail-closed predicate rules as control_flow.py, over
  // sample values the user types. Nothing runs and nothing leaves boltrig.
  const sampleRefs = useMemo(() => {
    const refs: string[] = [];
    for (const step of draft.steps) {
      if (step.action.trim() !== "flow.branch") continue;
      for (const ref of predicateSampleRefs(parseParamsOrEmpty(step.paramsText))) {
        if (!refs.includes(ref)) refs.push(ref);
      }
    }
    return refs;
  }, [draft.steps]);

  const tryWalk = useMemo<TryWalkState | null>(() => {
    if (mode !== "try") return null;
    const lookup = (ref: string) => {
      const typed = tryValues[ref];
      // An untyped sample mirrors a missing field: the engine resolves it to
      // null, and a null compares fail-closed rather than matching by luck.
      return typed === undefined || typed === "" ? null : coerceSampleText(typed);
    };
    const states = new Map<string, "ok" | "skipped">();
    const labels = new Map<string, string>();
    const steps = draft.steps.map((step) => ({
      id: step.id.trim(),
      action: step.action.trim(),
      parents: step.parents,
      branchArm: step.branchArm,
      params: parseParamsOrEmpty(step.paramsText),
    }));
    for (const step of steps) {
      if (step.parents.length === 0) {
        states.set(step.id, "ok");
        if (step.action === "flow.branch") {
          labels.set(step.id, selectBranchLabel(step.params, lookup));
        }
      }
    }
    let changed = true;
    let guard = 0;
    while (changed && guard++ < 200) {
      changed = false;
      for (const step of steps) {
        if (states.has(step.id)) continue;
        const parents = step.parents;
        // A parent that does not exist never finishes, so the step stays
        // "not reached" — the honest mirror of a walk that cannot schedule it.
        if (!parents.every((parent) => states.has(parent))) continue;
        let skipped = parents.some((parent) => states.get(parent) === "skipped");
        if (!skipped && step.branchArm) {
          // Mirrors control_flow.branch_matches: the declared arm must match
          // every parent that produced a branch label.
          skipped = parents.some((parent) => (
            labels.has(parent) && labels.get(parent) !== step.branchArm
          ));
        }
        states.set(step.id, skipped ? "skipped" : "ok");
        if (!skipped && step.action === "flow.branch") {
          labels.set(step.id, selectBranchLabel(step.params, lookup));
        }
        changed = true;
      }
    }
    return { states, labels };
  }, [mode, draft.steps, tryValues]);

  // Read-only spec pane: exactly what Save would send through the governed
  // authoring route, or the preserved stored definition when Save is disabled.
  const spec = useMemo(() => {
    try {
      return {
        text: JSON.stringify(buildWorkflowRequest(draft), null, 2),
        preserved: false,
      };
    } catch {
      return {
        text: JSON.stringify(
          { id: draft.id, version: draft.version, definition: draft.baseDefinition },
          null,
          2,
        ),
        preserved: true,
      };
    }
  }, [draft]);

  // Header summary lines, both from real data only. The touches line derives
  // adapter/agent names from VerbInfo.binding rather than any invented
  // noun-to-product table; with no registry it is omitted, not guessed.
  const triggerSummary = props.hasSchedule
    ? `cron ${props.cron} ${props.timezone}`
      + (props.scheduleState
        ? ` · scheduler ${props.scheduleState.observed.status.replace("_", " ")}`
        : "")
      + (props.scheduleState?.observed.next_run_at
        ? ` · next ${props.scheduleState.observed.next_run_at}`
        : "")
    : props.triggers.length > 0
      ? `${props.triggers.length} event ${props.triggers.length === 1 ? "binding" : "bindings"} · also starts by hand`
      : "Started by hand — nothing else starts it";
  const touchesSummary = useMemo(() => {
    if (verbs.length === 0) return null;
    const touched: string[] = [];
    let high = 0;
    for (const step of draft.steps) {
      const verb = verbById.get(step.action.trim());
      if (!verb) continue;
      if (verb.consequence === "high") high += 1;
      const ref = verb.binding?.target_ref;
      if (ref && !touched.includes(ref)) touched.push(ref);
    }
    const touchText = touched.length > 0
      ? `Touches ${joinNames(touched)}`
      : "Touches nothing outside boltrig";
    const highText = high > 0
      ? `${high} high-consequence ${high === 1 ? "step" : "steps"} can pause for approval`
      : "no high-consequence steps";
    return `${touchText} · ${highText}`;
  }, [draft.steps, verbById, verbs.length]);

  const stepIndexOf = (id: string) => (
    draft.steps.findIndex((step) => step.id.trim() === id)
  );

  function addStepAfter(id: string) {
    const newId = nextStepId(draft.steps);
    const parent = draft.steps.find((step) => step.id.trim() === id);
    props.onDraft((current) => {
      const source = current.steps.find((step) => step.id.trim() === id);
      if (!source) return current;
      return {
        ...current,
        steps: [...current.steps, {
          id: nextStepId(current.steps),
          action: "",
          parents: [id],
          description: "",
          paramsText: "{}",
          loopBindingsText: "{}",
          branchArm: source.action.trim() === "flow.branch" ? "true" : "",
          parameterField: "params",
          baseRecord: {},
        }],
      };
    });
    if (parent) {
      setSelectedStepId(newId);
      setSelectedEdge(null);
    }
  }

  function duplicateStep(id: string) {
    const source = draft.steps.find((step) => step.id.trim() === id);
    if (!source || isPreservedUnsupportedStep(source)) return;
    const existing = new Set(draft.steps.map((step) => step.id.trim()));
    let copyId = `${id}-copy`;
    let suffix = 2;
    while (existing.has(copyId)) copyId = `${id}-copy-${suffix++}`;
    props.onDraft((current) => ({
      ...current,
      steps: [...current.steps, {
        ...source,
        id: copyId,
        baseRecord: {},
      }],
    }));
    setSelectedStepId(copyId);
    setSelectedEdge(null);
  }

  function removeStepById(id: string) {
    const index = stepIndexOf(id);
    if (index < 0) return;
    if (isPreservedUnsupportedStep(draft.steps[index])) return;
    props.onRemoveStep(index);
    if (selectedStepId === id) setSelectedStepId(null);
    setSelectedEdge((edge) => (
      edge && (edge.from === id || edge.to === id) ? null : edge
    ));
  }

  function linkSteps(from: string, to: string) {
    if (from === to) return;
    const index = stepIndexOf(to);
    if (index < 0 || stepIndexOf(from) < 0) return;
    const target = draft.steps[index];
    if (isPreservedUnsupportedStep(target)) return;
    if (target.parents.includes(from)) return;
    props.onStep(index, { parents: [...target.parents, from] });
  }

  function removeEdge(from: string, to: string) {
    const index = stepIndexOf(to);
    if (index < 0) return;
    const target = draft.steps[index];
    if (isPreservedUnsupportedStep(target)) return;
    props.onStep(index, {
      parents: target.parents.filter((parent) => parent !== from),
    });
    setSelectedEdge(null);
  }

  function addStepAtEnd() {
    const newId = nextStepId(draft.steps);
    props.onAddStep();
    setSelectedStepId(newId);
    setSelectedEdge(null);
    setMode("edit");
  }

  function zoomBy(delta: number) {
    setZoom((current) => (
      Math.min(1.4, Math.max(0.4, Math.round((current + delta) * 100) / 100))
    ));
  }

  const problemsVisible = mode === "edit" && problems.length > 0;
  return (
    <main aria-label="Routine workflow editor" className="workflow-editor">
      <header className="workflow-editor-head">
        <button className="rc-back" onClick={props.onBack} type="button">
          <svg aria-hidden fill="none" height="14" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" viewBox="0 0 24 24" width="14"><polyline points="15 18 9 12 15 6" /></svg>
          <span>Routines</span>
        </button>
        <div className="workflow-editor-identity">
          <div className="workflow-editor-title-line">
            <input
              aria-label="Workflow id"
              className="workflow-title-input"
              placeholder="workflow-id"
              value={draft.id}
              onChange={(event) => props.onDraft((current) => ({ ...current, id: event.target.value }))}
            />
            <span className="workflow-editor-version">v{draft.version}</span>
            <span className="workflow-editor-source">{draft.source}</span>
          </div>
          <div className="rc-head-sub">
            <span className="rc-head-trigger">{triggerSummary}</span>
            {touchesSummary && <span>{touchesSummary}</span>}
          </div>
        </div>
        <div
          aria-label="Routine canvas controls"
          className="workflow-editor-controls"
          role="toolbar"
        >
          {props.dirty && (
            <div className="workflow-editor-dirty-actions">
              <span className="workflow-editor-change-state">unsaved changes</span>
              <button className="secondary-button" disabled={props.busy} onClick={props.onDiscard}>Discard</button>
              <button
                aria-label="Save"
                className="workflow-save-version"
                disabled={props.busy || draft.preservationErrors.length > 0}
                onClick={props.onSave}
                type="button"
              >
                {props.busy ? "Working…" : "Save a new version"}
              </button>
            </div>
          )}
          <div aria-label="Canvas mode" className="rc-seg" role="group">
            {(["edit", "last", "try"] as CanvasMode[]).map((value) => (
              <button
                data-active={mode === value ? "true" : undefined}
                key={value}
                onClick={() => setMode(value)}
                type="button"
              >
                {value === "edit" ? "Edit" : value === "last" ? "Last run" : "Try it"}
              </button>
            ))}
          </div>
          <div aria-label="Canvas zoom" className="rc-zoom" role="group">
            <button aria-label="Zoom out" onClick={() => zoomBy(-0.1)} title="Zoom out" type="button">−</button>
            <button
              aria-label="Fit the whole routine"
              className="rc-zoom-fit"
              onClick={() => setFitRequest((request) => request + 1)}
              title="Fit the whole routine"
              type="button"
            >
              {Math.round(zoom * 100)}%
            </button>
            <button aria-label="Zoom in" onClick={() => zoomBy(0.1)} title="Zoom in" type="button">+</button>
          </div>
          <button
            className="workflow-spec-button"
            data-active={specOpen ? "true" : undefined}
            onClick={() => setSpecOpen((open) => !open)}
            type="button"
          >
            {specOpen ? "Hide the spec" : "Show the spec"}
          </button>
          <button
            aria-label="Run now"
            className="workflow-start-button"
            disabled={props.busy || props.dirty || props.status === "archived"}
            onClick={props.onRunNow}
            type="button"
          >
            <svg aria-hidden fill="currentColor" height="12" viewBox="0 0 24 24" width="12"><polygon points="6 4 20 12 6 20" /></svg>
            <span>Start it now</span>
          </button>
        </div>
      </header>
      <details className="workflow-meta-details">
        <summary>Routine details</summary>
        <section className="workflow-meta">
          <span className={`status-pill ${props.status}`}>{props.status}</span>
          <label><span>Version</span><input className="field-control" value={draft.version} onChange={(event) => props.onDraft((current) => ({ ...current, version: event.target.value }))} /></label>
          <div className="workflow-source-readonly">
            <span>Source</span>
            <strong>{draft.source}</strong>
            <small>Assigned by Boltrig</small>
          </div>
          <label><span>Intent tags</span><input className="field-control" value={draft.tagsText} onChange={(event) => props.onDraft((current) => ({ ...current, tagsText: event.target.value }))} /></label>
        </section>
      </details>
      <section className="dag-section">
        {draft.preservationErrors.length > 0 && (
          <div className="workflow-preservation-warning" role="alert">
            <strong>Read-only definition</strong>
            <span>{draft.preservationErrors.join(" ")}</span>
            <span>Worker has disabled Save so the original step data cannot be lost.</span>
          </div>
        )}
        <div aria-label="Routine canvas editor" className="rc-section" role="region">
          <div className="rc-body">
            {draft.steps.length === 0 ? (
              <p className="dag-empty" style={{ flex: 1, margin: 16 }}>
                Add the first step. An empty workflow is valid but does no work.
              </p>
            ) : (
              <RoutineCanvas
                layoutKey={props.sessionKey}
                locked={draft.preservationErrors.length > 0}
                mode={mode}
                problems={problems}
                runSteps={mode === "last" ? runSteps : null}
                selectedEdge={selectedEdge}
                selectedStepId={selectedStepId}
                steps={draft.steps}
                tryWalk={tryWalk}
                verbById={verbById}
                fitRequest={fitRequest}
                onAddAfter={addStepAfter}
                onDuplicateStep={duplicateStep}
                onLinkSteps={linkSteps}
                onRemoveEdge={removeEdge}
                onRemoveStep={removeStepById}
                // ⌘S honours the same guards as the Save button; saveWorkflow
                // additionally refuses re-entry while a save is in flight.
                onRequestSave={() => {
                  if (!props.busy && draft.preservationErrors.length === 0) props.onSave();
                }}
                onSelectEdge={setSelectedEdge}
                onSelectStep={(id) => {
                  setSelectedStepId(id);
                  if (id !== null) setSelectedEdge(null);
                }}
                onZoomChange={setZoom}
                zoom={zoom}
              />
            )}
            <aside aria-label="Routine rail" className="rc-rail">
              <div aria-label="Routine rail views" className="rc-rail-tabs" role="tablist">
                <button aria-selected="true" data-active="true" role="tab" type="button">Step</button>
                <button
                  aria-label="Build with chat (unavailable)"
                  aria-selected="false"
                  disabled
                  role="tab"
                  title="Unavailable in this build — chat-based routine setup is not available."
                  type="button"
                >
                  Build with chat
                </button>
              </div>
              <div className="rc-rail-scroll">
              {specOpen ? (
                <div className="rc-spec">
                  <span style={{ fontSize: "13px" }}>The spec</span>
                  <p>
                    A routine is data, not code.
                    {spec.preserved
                      ? " Shown as stored: the current draft cannot be serialized — either this definition is preserved read-only, or a field is not valid JSON yet."
                      : " This is exactly what Save sends."}
                  </p>
                  <pre aria-label="Workflow spec JSON">{spec.text}</pre>
                </div>
              ) : (
                <>
                  {mode === "try" && (
                    <div className="rc-try">
                      <span style={{ fontSize: "13px" }}>Try it</span>
                      <p>
                        {sampleRefs.length > 0
                          ? "Type sample values for the fields the branches compare. The lit path is the one the engine would take with those values."
                          : "No branch in this routine compares a value, so every reachable step would run."}
                      </p>
                      {sampleRefs.map((ref) => (
                        <label key={ref}>
                          <span>{ref}</span>
                          <input
                            className="field-control"
                            value={tryValues[ref] ?? ""}
                            onChange={(event) => setTryValues((current) => ({
                              ...current,
                              [ref]: event.target.value,
                            }))}
                          />
                        </label>
                      ))}
                    </div>
                  )}
                  {mode === "last" && !runSteps && (
                    <div className="rc-facts">
                      <p className="rc-fact" data-tone="amber">
                        <span className="rc-fact-dot" />
                        <span>
                          No run record is readable here. A per-step record is
                          returned only when a run starts from this screen with
                          Start it now; queued and scheduled runs keep their receipts
                          in Schedule occurrences below.
                        </span>
                      </p>
                    </div>
                  )}
                  <StepInspector
                    cron={props.cron}
                    draft={draft}
                    hasSchedule={props.hasSchedule}
                    loopBodyIds={loopBodyIds}
                    mode={mode}
                    problems={problems}
                    runSteps={mode === "last" ? runSteps : null}
                    scheduleState={props.scheduleState}
                    selectedEdge={selectedEdge}
                    selectedStepId={selectedStepId}
                    timezone={props.timezone}
                    triggers={props.triggers}
                    verbById={verbById}
                    verbs={verbs}
                    onAddStep={addStepAtEnd}
                    onDuplicateStep={duplicateStep}
                    onRemoveEdge={removeEdge}
                    onRemoveStep={(index) => {
                      const step = draft.steps[index];
                      if (step) removeStepById(step.id.trim());
                    }}
                    onSelectStep={(id) => {
                      setSelectedStepId(id);
                      if (id !== null) setSelectedEdge(null);
                    }}
                    onStep={props.onStep}
                  />
                </>
              )}
              </div>
            </aside>
          </div>
          <div aria-label="Routine validation footer" className="rc-foot" role="region">
            {problemsVisible ? (
              <>
                <span className="rc-problems-head">
                  {problems.length === 1
                    ? "One thing to fix"
                    : `${problems.length} things to fix`}
                </span>
                {problems.map((problem) => (
                  <button
                    className="rc-problem"
                    data-tone={problem.tone}
                    key={`${problem.stepId}:${problem.text}`}
                    onClick={() => {
                      setMode("edit");
                      setSelectedStepId(problem.stepId);
                      setSelectedEdge(null);
                    }}
                    type="button"
                  >
                    <span className="rc-problem-dot" />
                    <span style={{ flex: 1, minWidth: 0 }}>{problem.text}</span>
                  </button>
                ))}
              </>
            ) : (
              <div className="rc-foot-ok">
                <span className="rc-foot-dot" />
                <p>
                  {mode === "last"
                    ? runSteps && props.lastExecution
                      ? `Showing the recorded result from run ${props.lastExecution.run_id} (${props.lastExecution.status}).`
                      : "No step-by-step result is available for this routine in this session."
                    : mode === "try"
                      ? "Sample values only — nothing ran and nothing left boltrig. An unrecognised comparison follows the safe path and does not continue."
                      : "This is the saved routine. Every action still follows your access and approval rules."}
                </p>
              </div>
            )}
          </div>
        </div>
        <datalist id="worker-actions">{authoredActions.map((id) => <option value={id} key={id}>{actionConsequences.has(id) ? `${actionConsequences.get(id)} consequence` : "built-in workflow control"}</option>)}</datalist>
      </section>
      <details className="workflow-advanced">
        <summary>Scheduling, triggers, and history</summary>
        <div className="workflow-advanced-body">
      <section className="workflow-schedule">
        <div>
          <p className="eyebrow">Cron schedule</p>
          <p>Desired state is stored here; observed state comes from the durable fleet scheduler.</p>
          {props.scheduleState && (
            <small role="status">
              Observed: {props.scheduleState.observed.status.replace("_", " ")}
              {props.scheduleState.observed.reason
                ? ` · ${scheduleReason(props.scheduleState.observed.reason)}`
                : ""}
              {props.scheduleState.observed.next_run_at
                ? ` · next ${props.scheduleState.observed.next_run_at}`
                : ""}
            </small>
          )}
        </div>
        <input aria-label="Cron expression" className="field-control" value={props.cron} onChange={(event) => props.onCron(event.target.value)} />
        <input aria-label="Schedule timezone" className="field-control" value={props.timezone} onChange={(event) => props.onTimezone(event.target.value)} />
        <button className="secondary-button" disabled={props.busy || props.dirty || props.status === "archived"} onClick={props.onSchedule}>Save schedule</button>
        {props.hasSchedule && props.status === "active" && (
          <button className="secondary-button" disabled={props.busy || props.dirty} onClick={props.onUnschedule}>Unschedule</button>
        )}
        {props.status === "active" ? (
          <button className="danger-button" disabled={props.busy || props.dirty} onClick={props.onArchive}>Archive workflow</button>
        ) : (
          <button className="secondary-button" disabled={props.busy || props.dirty} onClick={props.onRestore}>Restore workflow</button>
        )}
      </section>
      <section className="workflow-occurrences">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Schedule occurrences</p>
            <p>
              Enqueue is at-least-once. Each row follows one stable logical run
              through claim, engine acceptance, and terminal workflow outcome.
            </p>
          </div>
          <small role="note">
            Selected historical backfill unavailable: it cannot reuse the
            canonical observed-occurrence claim without widening authority.
          </small>
        </div>
        {props.occurrenceFinalization && (
          <div className="workflow-occurrence-finalization" role="status">
            <strong>
              {occurrenceFinalizationCopy(props.occurrenceFinalization)[0]}
            </strong>
            <p>{occurrenceFinalizationCopy(props.occurrenceFinalization)[1]}</p>
            {(props.occurrenceFinalization === "waiting"
              || props.occurrenceFinalization === "unavailable") && (
              <button
                className="secondary-button"
                disabled={props.busy}
                onClick={props.onFinalizeOccurrenceRetry}
              >
                Check approval and continue exact retry
              </button>
            )}
          </div>
        )}
        {props.scheduleOccurrences.length === 0 ? (
          <p className="dag-empty">No schedule occurrence receipts recorded.</p>
        ) : (
          <div className="workflow-occurrence-list">
            {props.scheduleOccurrences.map((occurrence) => (
              <article key={`${occurrence.scheduled_for}:${occurrence.run_id}`}>
                <div>
                  <strong>{occurrence.scheduled_for}</strong>
                  <small>
                    {occurrence.run_id} · {occurrence.status}
                    {occurrence.reason
                      ? ` · ${scheduleOccurrenceReason(occurrence.reason)}`
                      : ""}
                  </small>
                  <small>
                    {occurrence.retry.attempts} dispatch attempt
                    {occurrence.retry.attempts === 1 ? "" : "s"}
                    {` · ${occurrence.retry.manual_retries} manual retries`}
                    {occurrence.enqueued_at
                      ? ` · enqueued ${occurrence.enqueued_at}`
                      : ""}
                    {occurrence.outcome_at
                      ? ` · outcome ${occurrence.outcome_at}`
                      : ""}
                  </small>
                  {occurrence.engine_outcome.status === "pending_or_unknown" && (
                    <small role="note">
                      Outcome is pending or unknown. Automatic Hatchet terminal
                      status reconciliation is unavailable.
                    </small>
                  )}
                </div>
                {occurrence.status === "failed" && (
                  <button
                    className="secondary-button"
                    disabled={props.busy || props.dirty || props.status === "archived"}
                    onClick={() => props.onRetryOccurrence(occurrence)}
                  >
                    Retry same run
                  </button>
                )}
              </article>
            ))}
          </div>
        )}
        {props.scheduleHistoryTruncated && (
          <small>Showing the newest 25 bounded receipts.</small>
        )}
      </section>
      <WorkflowTriggersPanel
        workflowId={draft.id}
        dirty={props.dirty}
        busy={props.busy}
        status={props.status}
        triggers={props.triggers}
        channels={props.channels}
        deliveries={props.triggerDeliveries}
        secret={props.triggerSecret}
        pending={props.pendingTrigger}
        onCreate={props.onCreateTrigger}
        onAction={props.onTriggerAction}
        onLoadDeliveries={props.onLoadTriggerDeliveries}
        onDismissSecret={props.onDismissTriggerSecret}
        onFinalize={props.onFinalizeTrigger}
        onRefreshApproval={props.onRefreshTriggerApproval}
        onDraftChange={props.onTriggerDraftChange}
      />
      <section className="workflow-run-history">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Run history</p>
            <p>
              {props.runStat
                ? `${props.runStat.run_count} recorded · ${props.runStat.success_count} successful`
                : "No recorded runs for this workflow."}
            </p>
          </div>
          <div className="inline-actions">
            <button
              className="secondary-button"
              disabled={props.busy || props.dirty || props.status === "archived"}
              onClick={props.onQueue}
              type="button"
            >
              Queue run
            </button>
            <a className="secondary-button" href="#/runs">Inspect runs</a>
          </div>
        </div>
        {props.runIds.length > 0 && (
          <div className="skill-list" aria-label="Recent workflow run identifiers">
            {props.runIds.slice(0, 10).map((runId) => <span key={runId}>{runId}</span>)}
          </div>
        )}
        {props.lastExecution && (
          <div className="detail-section">
            <p className="eyebrow">Latest immediate execution · {props.lastExecution.status}</p>
            {props.lastExecution.steps.map((step) => (
              <div className="audit-line" key={step.id}>
                <span className={`activity-dot ${step.status === "ok" ? "ok" : step.status === "paused" ? "pending" : "error"}`} />
                <span>{step.id}<small>{step.action ?? "control step"} · {step.status}</small></span>
              </div>
            ))}
          </div>
        )}
      </section>
      {props.message && <p className="notice workflow-notice" role="status">{props.message}</p>}
        </div>
      </details>
    </main>
  );
}

interface WorkflowTriggersPanelProps {
  workflowId: string;
  dirty: boolean;
  busy: boolean;
  status: "active" | "archived";
  triggers: WorkflowTriggerSummary[];
  channels: ChannelSummary[];
  deliveries: WorkflowTriggerDelivery[];
  secret: { secret: string; webhookPath?: string } | null;
  pending: PendingTriggerMutation | null;
  onCreate: (
    name: string,
    source: WorkflowTriggerSource,
    channelId?: string,
  ) => void;
  onAction: (
    trigger: WorkflowTriggerSummary,
    action: "enable" | "disable" | "rotate",
  ) => void;
  onLoadDeliveries: (triggerId: string) => void;
  onDismissSecret: () => void;
  onFinalize: () => void;
  onRefreshApproval: () => void;
  onDraftChange: () => void;
}

function WorkflowTriggersPanel(props: WorkflowTriggersPanelProps) {
  const [name, setName] = useState("");
  const [source, setSource] = useState<WorkflowTriggerSource>("webhook");
  const [channelId, setChannelId] = useState("");
  const cannotCreate = (
    props.busy
    || props.dirty
    || props.status === "archived"
    || !name.trim()
    || (source === "channel" && !channelId)
  );
  const pendingStatusCopy = !props.pending
    ? ""
    : props.pending.state === "ready"
      ? "It is approved and ready to finalize."
      : props.pending.state === "checking"
        ? "Checking the exact originator-owned approval request."
        : props.pending.state === "unavailable"
          ? props.pending.requestId
            ? "Its exact approval status is unavailable. Retry the check before finalizing."
            : "No approval request id was returned, so finalization is unavailable."
          : "An independent author must approve it in the originating chat first.";
  const pendingButtonLabel = props.pending?.state === "ready"
    ? "Finalize after approval"
    : props.pending?.state === "checking"
      ? "Checking approval…"
      : props.pending?.state === "unavailable"
        ? props.pending.requestId
          ? "Retry approval check"
          : "Approval check unavailable"
        : "Check approval status";

  return (
    <section className="workflow-triggers">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Event-source bindings</p>
          <p>Webhook and verified channel events enter as untrusted workflow input. Current identity and workspace authority are rechecked on every delivery.</p>
        </div>
      </div>
      <div className="workflow-trigger-form">
        <label>
          <span>Binding name</span>
          <input
            aria-label="Trigger binding name"
            className="field-control"
            value={name}
            onChange={(event) => {
              props.onDraftChange();
              setName(event.target.value);
            }}
          />
        </label>
        <label>
          <span>Source</span>
          <select
            aria-label="Trigger source"
            className="field-control"
            value={source}
            onChange={(event) => {
              props.onDraftChange();
              setSource(event.target.value as WorkflowTriggerSource);
            }}
          >
            <option value="webhook">Authenticated webhook</option>
            <option value="channel">Verified channel sender</option>
          </select>
        </label>
        {source === "channel" && (
          <label>
            <span>Channel</span>
            <select
              aria-label="Trigger channel"
              className="field-control"
              value={channelId}
              onChange={(event) => {
                props.onDraftChange();
                setChannelId(event.target.value);
              }}
            >
              <option value="">Choose an enabled channel</option>
              {props.channels.filter((channel) => channel.enabled).map((channel) => (
                <option value={channel.id} key={channel.id}>
                  {channel.name} · {channel.platform}
                </option>
              ))}
            </select>
          </label>
        )}
        <button
          className="secondary-button"
          disabled={cannotCreate}
          onClick={() => props.onCreate(name.trim(), source, channelId || undefined)}
        >
          Bind source
        </button>
      </div>
      {props.secret && (
        <div className="secret-once" role="status">
          <p className="eyebrow">Shown once</p>
          <strong>Copy the webhook secret now</strong>
          <code>{props.secret.secret}</code>
          {props.secret.webhookPath && (
            <code>{props.secret.webhookPath}</code>
          )}
          <p>Boltrig retains only the secret digest. A later list cannot reveal this value.</p>
          <button className="secondary-button" onClick={props.onDismissSecret}>I saved it</button>
        </div>
      )}
      {props.pending && (
        <div className="secret-once" role="status">
          <p className="eyebrow">Approval required</p>
          <strong>
            {props.pending.kind === "create"
              ? "Finalize the approved webhook binding"
              : "Finalize the approved secret rotation"}
          </strong>
          <p>
            {props.pending.requestId
              ? `Request ${props.pending.requestId}. `
              : "No request id is available. "}
            {pendingStatusCopy} Finalization
            replays the exact approved action and returns the one-time secret here.
          </p>
          <button
            className="secondary-button"
            disabled={
              props.busy
              || props.pending.state === "checking"
              || !props.pending.requestId
            }
            onClick={props.pending.state === "ready"
              ? props.onFinalize
              : props.onRefreshApproval}
            type="button"
          >
            {pendingButtonLabel}
          </button>
        </div>
      )}
      {props.triggers.length === 0 ? (
        <p className="dag-empty">No event sources are bound to {props.workflowId}.</p>
      ) : (
        <div className="workflow-trigger-list">
          {props.triggers.map((trigger) => (
            <article className="workflow-trigger-row" key={trigger.id}>
              <div>
                <strong>{trigger.name}</strong>
                <small>
                  {trigger.source}
                  {trigger.channel_id ? ` · ${trigger.channel_id}` : ""}
                  {` · ${trigger.enabled ? "enabled" : "disabled"}`}
                </small>
              </div>
              <div className="inline-actions">
                <button
                  className="secondary-button"
                  disabled={props.busy || props.dirty || props.status === "archived"}
                  onClick={() => props.onAction(
                    trigger, trigger.enabled ? "disable" : "enable",
                  )}
                >
                  {trigger.enabled ? "Disable" : "Enable"}
                </button>
                {trigger.source === "webhook" && (
                  <button
                    className="secondary-button"
                    disabled={props.busy || props.dirty}
                    onClick={() => props.onAction(trigger, "rotate")}
                  >
                    Rotate secret
                  </button>
                )}
                <button
                  className="secondary-button"
                  onClick={() => props.onLoadDeliveries(trigger.id)}
                >
                  Delivery history
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
      {props.deliveries.length > 0 && (
        <div className="workflow-trigger-deliveries" aria-label="Trigger delivery history">
          {props.deliveries.map((delivery) => (
            <div className="audit-line" key={delivery.event_digest}>
              <span className={`activity-dot ${
                delivery.status === "queued" || delivery.status === "completed"
                  ? "ok"
                  : delivery.status === "pending_human"
                    ? "pending"
                    : "error"
              }`} />
              <span>
                {delivery.status}
                <small>
                  {delivery.authority_subject ?? "no authority"}
                  {delivery.reason ? ` · ${delivery.reason}` : ""}
                </small>
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function parseParamsOrEmpty(text: string): Record<string, unknown> {
  try {
    const parsed: unknown = JSON.parse(text.trim() || "{}");
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
  } catch {
    // Malformed JSON already surfaces through validateWorkflowDraft; the
    // canvas simply treats it as an empty predicate rather than crashing.
  }
  return {};
}

function joinNames(items: string[]): string {
  if (items.length === 0) return "nothing";
  if (items.length === 1) return items[0];
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

function scheduleOf(definition: Record<string, unknown>): { cron: string; timezone: string } | null {
  const value = definition.schedule;
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const schedule = value as Record<string, unknown>;
  if (schedule.type !== "cron" || typeof schedule.cron !== "string") return null;
  return {
    cron: schedule.cron,
    timezone: typeof schedule.timezone === "string" ? schedule.timezone : "UTC",
  };
}

function normalizeExactResult<T extends GovernedResult>(
  result: T,
): ExactAutomationResult {
  return {
    status: result.status,
    hitl_request_id: result.hitl_request_id,
    reason: result.reason,
    value: result as ExactAutomationResult["value"],
  };
}

function isPendingHuman<T>(
  result: T,
): result is T & { status: "pending_human"; hitl_request_id?: string } {
  return Boolean(
    result
    && typeof result === "object"
    && (result as { status?: unknown }).status === "pending_human",
  );
}

function routeInputEquals(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function scheduleMutationMessage(
  result: ScheduleWorkflowResponse | undefined,
): string {
  const observed = result?.schedule_state?.observed;
  if (observed?.status === "needs_action") {
    return `Schedule desired state saved, but action is required: ${scheduleReason(observed.reason)}.`;
  }
  if (observed?.status === "unavailable") {
    return `Schedule desired state saved, but execution is unavailable: ${scheduleReason(observed.reason)}.`;
  }
  return "Schedule desired state saved. Waiting for worker reconciliation.";
}

function scheduleReason(reason: string | null) {
  const labels: Record<string, string> = {
    scheduling_authority_not_bound: "bind a current human scheduling authority",
    scheduling_authority_revoked: "the scheduling user is no longer active",
    scheduling_workspace_membership_revoked: "the scheduling user left this workspace",
    scheduling_trigger_grant_revoked: "the scheduling user can no longer trigger workflows",
    durable_executor_required: "a durable Hatchet executor is required",
    scheduled_workflow_unavailable: "the stored workflow is unavailable",
    scheduled_workflow_archived: "the workflow is archived",
    missed_occurrences_truncated: "older missed occurrences were skipped after bounded catch-up",
  };
  return reason ? labels[reason] ?? reason.replaceAll("_", " ") : "";
}

function scheduleOccurrenceReason(reason: string) {
  const reasons: Record<string, string> = {
    manual_retry_requested: "manual retry requested",
    schedule_dispatch_failed: "executor submission failed",
    workflow_execution_failed: "workflow execution failed",
    occurrence_snapshot_changed: "workflow or schedule changed",
    scheduled_workflow_unavailable: "workflow unavailable",
    scheduled_workflow_archived: "workflow archived",
    scheduling_authority_not_bound: "schedule authority not bound",
    scheduling_authority_revoked: "schedule authority revoked",
    scheduling_workspace_membership_revoked: "workspace membership revoked",
    scheduling_trigger_grant_revoked: "workflow trigger grant revoked",
    durable_executor_required: "durable executor required",
    workflow_occurrence_failed: "occurrence failed",
  };
  return reasons[reason] ?? "occurrence failed";
}

function occurrenceFinalizationCopy(
  state: Exclude<OccurrenceFinalizationState, null>,
): [string, string] {
  if (state === "waiting") {
    return [
      "Waiting for a decision in the originating chat",
      "After an independent decision, check again to replay only this exact failed occurrence.",
    ];
  }
  if (state === "checking") {
    return [
      "Checking approval…",
      "No occurrence state is inferred until the kernel responds.",
    ];
  }
  if (state === "rejected") {
    return ["Retry rejected", "The occurrence remains failed."];
  }
  if (state === "expired") {
    return [
      "Retry approval expired",
      "The expired decision cannot authorize a replay.",
    ];
  }
  if (state === "consumed") {
    return [
      "Retry approval already consumed",
      "Refresh the occurrence before considering another recovery action.",
    ];
  }
  if (state === "invalidated") {
    return [
      "Pending occurrence retry changed",
      "The workflow selection, definition, schedule, or receipt changed. The old approval will not be applied.",
    ];
  }
  return [
    "Approval status unavailable",
    "No retry is inferred. Check again after approval status is available.",
  ];
}

function actionLabel(
  action: "unschedule" | "archive" | "restore" | "enable" | "disable" | "rotate",
) {
  return action[0]!.toUpperCase() + action.slice(1);
}

function lifecyclePastTense(action: "unschedule" | "archive" | "restore") {
  if (action === "unschedule") return "unscheduled";
  if (action === "archive") return "archived";
  return "restored";
}

// --- The routine picker -----------------------------------------------------
// The decided target opens Routines as a picker rather than a table: a card per
// routine showing its own graph, so you recognise one by its shape before you
// read its name. Opening a card routes into the editor that already exists.

function routineWhen(value: string | null | undefined): string {
  if (!value) return "never run";
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return "never run";
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function RoutinePicker({
  workflows,
  stats,
  onOpen,
  onNew,
}: {
  workflows: WorkflowSummary[];
  stats: Record<string, WorkflowRunStat>;
  onOpen(id: string, focusStep?: string): void;
  onNew(): void;
}) {
  type PreviewState =
    | { status: "loading" }
    | { status: "ready"; steps: WorkflowStepDefinition[] }
    | { status: "unavailable" };
  const [previews, setPreviews] = useState<Record<string, PreviewState>>({});
  const previewRequests = useRef<Record<string, number>>({});

  const loadPreview = useCallback(async (id: string) => {
    const request = (previewRequests.current[id] ?? 0) + 1;
    previewRequests.current[id] = request;
    setPreviews((current) => ({
      ...current,
      [id]: { status: "loading" },
    }));
    let next: PreviewState;
    try {
      const detail = await client.workflow(id);
      const list = detail.definition?.steps;
      next = Array.isArray(list)
        ? { status: "ready", steps: list as WorkflowStepDefinition[] }
        : { status: "unavailable" };
    } catch {
      next = { status: "unavailable" };
    }
    if (previewRequests.current[id] !== request) return;
    setPreviews((current) => ({ ...current, [id]: next }));
  }, []);

  // The State word runs the same shared graph checks as the canvas Problems
  // strip, over the same steps already fetched for the thumbnail, so the card
  // and the editor can never disagree about what needs fixing.
  const problemsById = useMemo(() => {
    const map: Record<string, GraphProblem[]> = {};
    for (const [id, preview] of Object.entries(previews)) {
      if (preview.status === "ready") {
        map[id] = checkDefinitionSteps(preview.steps);
      }
    }
    return map;
  }, [previews]);

  // Summaries carry no steps, so every graph is read from its detail. Loading
  // and failed reads remain explicit states: neither may be projected as an
  // empty, healthy routine.
  useEffect(() => {
    const ids = workflows.map((workflow) => workflow.id);
    setPreviews(Object.fromEntries(ids.map((id) => [id, { status: "loading" }])));
    for (const id of ids) void loadPreview(id);
    return () => {
      for (const id of ids) {
        previewRequests.current[id] = (previewRequests.current[id] ?? 0) + 1;
      }
    };
  }, [loadPreview, workflows]);

  return (
    <>
    {workflows.length === 0 && <p className="muted small">No saved workflows yet.</p>}
    <div className="console-cards">
      <button className="routine-new" onClick={onNew} type="button">
        <span className="routine-new-plus" aria-hidden>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
          </svg>
        </span>
        <span className="routine-new-title">New routine</span>
        <span className="routine-new-sub">
          An empty routine with a chat in it. Ask it to read a run that went
          well, or say what should happen.
        </span>
      </button>
      {workflows.map((workflow) => {
        const preview = previews[workflow.id] ?? { status: "loading" as const };
        const stat = stats[workflow.id];
        const runs = stat?.run_count ?? 0;
        const failed = runs > 0 && (stat?.success_count ?? 0) < runs;
        const tone = runs === 0 ? "unknown" : failed ? "red" : "green";
        const scheduled = Boolean(workflow.schedule);
        const observed = workflow.schedule_state?.observed.status;
        const needsYou = observed === "needs_action";
        const problems = problemsById[workflow.id] ?? [];
        // Precedence: broken graph > scheduler waiting on a person > archived
        // > runs unattended on a schedule > started by hand.
        const stateWord = preview.status === "loading"
          ? "Loading preview"
          : preview.status === "unavailable"
            ? "Preview unavailable"
            : problems.length > 0
              ? `${problems.length} to fix`
              : needsYou
                ? "needs you"
                : workflow.status === "archived"
                  ? "archived"
                  : scheduled ? "unattended" : "manual";
        return (
          <div className="routine-card-shell" key={workflow.id}>
            <button
              className="routine-card"
              onClick={() => onOpen(workflow.id, problems[0]?.stepId)}
              type="button"
            >
              <span className="routine-thumb">
                {preview.status === "ready" ? (
                  <RoutineThumb steps={preview.steps} />
                ) : (
                  <span
                    aria-hidden="true"
                    className="routine-preview-state"
                    data-state={preview.status}
                  >
                    {preview.status === "loading" ? "loading…" : "not available"}
                  </span>
                )}
              </span>
              <span className="routine-body">
                <span className="routine-name-row">
                  <span className="rail-dot" style={{ background: `var(--${tone})` }} />
                  <span className="routine-name">{workflow.id}</span>
                  <span className="routine-version">v{workflow.version}</span>
                </span>
                <span className="routine-sub">
                  {(workflow.intent_tags ?? []).length > 0
                    ? (workflow.intent_tags ?? []).join(", ")
                    : `Held as data, from ${workflow.source}`}
                </span>
                <span style={{ flex: 1 }} />
                <span className="routine-foot-row">
                  <span className="routine-starts">
                    {scheduled
                      ? `${workflow.schedule?.cron} ${workflow.schedule?.timezone}`
                      : "Nothing starts it on a schedule"}
                    {workflow.schedule_state?.desired.status === "active"
                      ? ` \u00b7 scheduler ${workflow.schedule_state.observed.status.replace("_", " ")}`
                      : ""}
                  </span>
                  <span
                    className="routine-state"
                    data-tone={preview.status === "ready" && (problems.length > 0 || needsYou)
                      ? "needs"
                      : undefined}
                  >
                    {stateWord}
                  </span>
                  <span className="routine-when" data-tone={failed ? "failed" : undefined}>
                    {routineWhen(stat?.last_run_at)}
                  </span>
                </span>
              </span>
            </button>
            {preview.status === "unavailable" && (
              <button
                aria-label={`Retry preview for ${workflow.id}`}
                className="routine-preview-retry"
                onClick={() => void loadPreview(workflow.id)}
                type="button"
              >
                Retry
              </button>
            )}
          </div>
        );
      })}
    </div>
    <RecentlyChanged />
    </>
  );
}
