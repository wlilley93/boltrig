import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { RoutineThumb } from "./RoutineThumb";
import { Topbar, Unavailable } from "./Shell";

type PendingTriggerMutation =
  | {
      kind: "create";
      requestId: string;
      name: string;
      source: "webhook";
      state: "waiting" | "ready";
    }
  | {
      kind: "rotate";
      requestId: string;
      trigger: WorkflowTriggerSummary;
      state: "waiting" | "ready";
    };
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
  const [listNotice, setListNotice] = useState("");
  const [detailError, setDetailError] = useState("");
  const exactApprovalInvalidator = useRef<() => void>(() => undefined);
  selectedWorkflowIdRef.current = selectedWorkflowId;

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
        setWorkflows([]);
        setDraft(null);
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
    setBusy(true);
    setMessage("");
    setDetailError("");
    setDraft(null);
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
    if (!draft) return;
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
        setMessage("Save is waiting for approval in Inbox.");
      } else if (result.status === "ok") {
        setDirty(false);
        setMessage("Workflow saved through the governed authoring route.");
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
        setMessage("Schedule change is waiting for approval in Inbox.");
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
        setMessage(`${actionLabel(action)} is waiting for approval in Inbox.`);
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
        setMessage("Occurrence retry is waiting for approval in Inbox.");
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
        // the second Inbox decision stays redeemable.
        setPendingOccurrenceRetry({
          ...pending,
          approvalId: result.hitl_request_id,
          invalidated: false,
        });
        setOccurrenceFinalization("waiting");
        setMessage("Occurrence retry is waiting for a fresh approval in Inbox.");
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
        setMessage("Run is waiting for approval in Inbox.");
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
        setMessage("Execution is waiting for approval in Inbox.");
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
          setPendingTrigger({
            kind: "create",
            requestId: result.hitl_request_id ?? "",
            name,
            source,
            state: "waiting",
          });
          setMessage(
            "Webhook binding is waiting for approval. After approval, finalize it here to receive the one-time secret.",
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
          setMessage("Trigger binding is waiting for approval in Inbox.");
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
          setPendingTrigger({
            kind: "rotate",
            requestId: result.hitl_request_id ?? "",
            trigger,
            state: "waiting",
          });
          setMessage(
            "Secret rotation is waiting for approval. After approval, finalize it here to receive the new one-time secret.",
          );
        } else {
          exactApproval.begin({
            kind: "trigger_lifecycle",
            workflowId: draft.id,
            triggerId: trigger.id,
            action,
          }, result, `Trigger ${action}`);
          setMessage(`${actionLabel(action)} is waiting for approval in Inbox.`);
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
    try {
      const result = await client.workflowTriggerDeliveries(draft.id, triggerId);
      setTriggerDeliveries(result.deliveries);
    } catch {
      setMessage("Trigger delivery history is unavailable in this workspace.");
    }
  }

  function finalizeTriggerMutation() {
    if (!pendingTrigger) return;
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
    <div className="page">
      <Topbar title="Routines" status={surfaceState === "loading" ? "Loading…" : surfaceState === "ready" ? `${workflows.length} workflows` : surfaceState === "denied" ? "Restricted" : "Unavailable"} />
      <div className="page-content">
        <div className="page-intro">
          <div>
            <h2>Routines</h2>
            <p>Steps boltrig repeats the same way every time, held as data rather than code. Each one is a graph: what starts it, then steps that wait on the steps before them. Every step names a scoped verb, and saves, approvals, runs, credentials and Hatchet handoff stay behind the kernel.</p>
          </div>
          {surfaceState === "ready" && <button className="primary-button" onClick={newWorkflow}>New routine</button>}
        </div>
        {listNotice && <p className="notice" role="status">{listNotice}</p>}
        {detailError && <p className="notice" role="alert">{detailError}</p>}
        <ExactApprovalFinalizer controller={exactApproval} />
        {surfaceState === "loading" && <Unavailable title="Loading automations">Loading the governed workflow library.</Unavailable>}
        {surfaceState === "denied" && <Unavailable title="Automation access denied">Your current role cannot view or author workflows.</Unavailable>}
        {surfaceState === "unavailable" && <Unavailable title="Automations unavailable">The governed workflow library could not be reached.</Unavailable>}
        {surfaceState === "ready" && !draft && (
          <RoutinePicker
            onNew={newWorkflow}
            onOpen={(id) => { invalidateExactApproval(); setSelectedWorkflowId(id); }}
            onRefresh={() => void refreshList()}
            stats={stats}
            workflows={workflows}
          />
        )}
        {surfaceState === "ready" && draft && (
          <div className="automation-studio editor-open">
            <aside className="workflow-library" aria-label="Workflow library">
              <div className="workflow-library-head">
                <strong>Library</strong>
                <button className="icon-button" aria-label="Refresh workflows" onClick={() => void refreshList()}>↻</button>
              </div>
              {workflows.length === 0 && <p>No saved workflows yet.</p>}
              {workflows.map((workflow) => (
                <button
                  className={draft?.id === workflow.id ? "workflow-library-row active" : "workflow-library-row"}
                  key={workflow.id}
                  onClick={() => {
                    invalidateExactApproval();
                    setSelectedWorkflowId(workflow.id);
                  }}
                >
                  <strong>{workflow.id}</strong>
                  <small>
                    v{workflow.version} · {workflow.source}
                    {` · ${workflow.status ?? "active"}`}
                    {workflow.schedule
                      ? ` · ${workflow.schedule.cron} ${workflow.schedule.timezone}`
                      : " · unscheduled"}
                    {workflow.schedule_state?.desired.status === "active"
                      ? ` · scheduler ${workflow.schedule_state.observed.status.replace("_", " ")}`
                      : ""}
                    {stats[workflow.id] ? ` · ${stats[workflow.id].run_count} runs` : ""}
                  </small>
                </button>
              ))}
            </aside>
            {!draft ? (
              <Unavailable title="Choose or create a workflow">
                Worker now supports native dependency and step authoring. Operator remains available for advanced live-canvas inspection.
              </Unavailable>
            ) : (
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
            )}
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
  onCron: (value: string) => void;
  onTimezone: (value: string) => void;
  onTriggerDraftChange: () => void;
}

function WorkflowEditor(props: WorkflowEditorProps) {
  const { draft, verbs } = props;
  const authoredActions = useMemo(() => [
    ...WORKER_CONTROL_ACTIONS,
    ...verbs
      .map((verb) => verb.id)
      .filter((id) => !workflowActionLimitation(id)),
  ].filter((id, index, all) => all.indexOf(id) === index), [verbs]);
  const actionIds = useMemo(() => new Set(authoredActions), [authoredActions]);
  const actionConsequences = useMemo(
    () => new Map(verbs.map((verb) => [verb.id, verb.consequence ?? "unknown"])),
    [verbs],
  );
  const actionByStepId = useMemo(
    () => new Map(draft.steps.map((step) => [step.id, step.action])),
    [draft.steps],
  );
  const loopBodyIds = useMemo(
    () => new Set(
      draft.steps
        .filter((step) => step.action === "flow.loop")
        .flatMap((step) => loopBodyStepIds(draft.steps, step.id)),
    ),
    [draft.steps],
  );
  return (
    <main className="workflow-editor">
      <header className="workflow-editor-head">
        <div>
          <p className="eyebrow">{props.dirty ? "Unsaved draft" : "Saved definition"}</p>
          <input
            aria-label="Workflow id"
            className="workflow-title-input"
            placeholder="workflow-id"
            value={draft.id}
            onChange={(event) => props.onDraft((current) => ({ ...current, id: event.target.value }))}
          />
        </div>
        <div className="inline-actions">
          <button className="secondary-button" disabled={props.busy || props.dirty || props.status === "archived"} onClick={props.onQueue}>Queue run</button>
          <button className="secondary-button" disabled={props.busy || props.dirty || props.status === "archived"} onClick={props.onRunNow}>Run now</button>
          <button className="primary-button" disabled={props.busy || draft.preservationErrors.length > 0} onClick={props.onSave}>{props.busy ? "Working…" : "Save"}</button>
        </div>
      </header>
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
      <section className="dag-section">
        <div className="dag-heading">
          <div><p className="eyebrow">Dependency graph</p><p>{verbs.length ? `${verbs.length} scoped actions available` : "Scoped action registry unavailable; existing actions remain visible."}</p></div>
          <button className="secondary-button" onClick={props.onAddStep}>Add step</button>
        </div>
        {draft.preservationErrors.length > 0 && (
          <div className="workflow-preservation-warning" role="alert">
            <strong>Read-only definition</strong>
            <span>{draft.preservationErrors.join(" ")}</span>
            <span>Worker has disabled Save so the original step data cannot be lost.</span>
          </div>
        )}
        {draft.steps.length === 0 ? <p className="dag-empty">Add the first governed step. An empty workflow is valid but does no work.</p> : (
          <div className="dag-map">{draft.steps.map((step, index) => {
            const limitation = workflowActionLimitation(step.action);
            const locked = isPreservedUnsupportedStep(step);
            const hasBranchParent = step.parents.some(
              (parent) => actionByStepId.get(parent) === "flow.branch",
            );
            const branchEligible = Boolean(step.branchArm) || hasBranchParent;
            const legacyBranch = Boolean(
              step.branchArm && !["true", "false"].includes(step.branchArm),
            );
            return (
            <article className={`dag-step${locked ? " unsupported" : ""}`} key={`${index}-${step.id}`} aria-label={`Step ${step.id || index + 1}`}>
              <div className="dag-step-index">{index + 1}</div>
              <div className="dag-step-fields">
                <div className="dag-step-row">
                  <label><span>Step id</span><input className="field-control" disabled={locked} value={step.id} onChange={(event) => props.onStep(index, { id: event.target.value })} /></label>
                  <label><span>Governed action</span><input className="field-control" disabled={locked} list="worker-actions" value={step.action} onChange={(event) => props.onStep(index, { action: event.target.value })} /></label>
                  <label><span>Depends on</span><select className="field-control parent-select" disabled={locked} multiple value={step.parents} onChange={(event) => props.onStep(index, { parents: [...event.target.selectedOptions].map((option) => option.value) })}>{draft.steps.filter((_, candidate) => candidate !== index).map((candidate) => <option value={candidate.id} key={candidate.id}>{candidate.id || "unnamed"}</option>)}</select></label>
                </div>
                <label><span>Description</span><input className="field-control" disabled={locked} value={step.description} onChange={(event) => props.onStep(index, { description: event.target.value })} /></label>
                {branchEligible && (
                  <label>
                    <span>Branch arm</span>
                    <select
                      aria-label={`Branch arm for ${step.id || `step ${index + 1}`}`}
                      className="field-control"
                      disabled={locked}
                      value={step.branchArm}
                      onChange={(event) => props.onStep(index, { branchArm: event.target.value })}
                    >
                      <option value="">Always</option>
                      <option value="true">IF / true</option>
                      <option value="false">ELSE / false</option>
                      {legacyBranch && (
                        <option value={step.branchArm}>Existing unsupported label: {step.branchArm}</option>
                      )}
                    </select>
                    <small>Runs only when every branch-producing parent matches this arm.</small>
                  </label>
                )}
                <label><span>Parameters (JSON object)</span><textarea className="field-control params-editor" disabled={locked} value={step.paramsText} onChange={(event) => props.onStep(index, { paramsText: event.target.value })} /></label>
                {step.action === "flow.loop" && (
                  <small className="loop-contract-note" role="note">
                    Use exactly one item source: a literal <code>items</code> array or an
                    ancestor <code>items_from</code> reference such as
                    <code>$fetch.output.rows</code>. Boltrig runs at most 100 items in
                    stable array order; the selected values must fit 256 KiB.
                  </small>
                )}
                {(loopBodyIds.has(step.id) || step.loopBindingsText.trim() !== "{}") && (
                  <label>
                    <span>Loop bindings (JSON object)</span>
                    <textarea
                      aria-label={`Loop bindings for ${step.id || `step ${index + 1}`}`}
                      className="field-control params-editor"
                      disabled={locked}
                      value={step.loopBindingsText}
                      onChange={(event) => props.onStep(index, {
                        loopBindingsText: event.target.value,
                      })}
                    />
                    <small>
                      Map an existing top-level parameter to <code>item</code> or
                      <code>index</code>. Values are replaced as typed JSON before the
                      governed action is schema-checked. Up to 32 bindings are allowed.
                    </small>
                  </label>
                )}
                {limitation && (
                  <small className="unsupported-action" role="note">
                    {limitation} {locked
                      ? "Worker preserves this existing step exactly and locks its fields."
                      : "Worker cannot author this action; choose a supported action before saving."}
                  </small>
                )}
                {!limitation && !actionIds.has(step.action) && <small className="unresolved-action">This action is not in the caller-scoped registry. It will fail closed unless available at run time.</small>}
              </div>
              <button className="danger-button" disabled={locked} aria-label={`Remove ${step.id || `step ${index + 1}`}`} onClick={() => props.onRemoveStep(index)}>Remove</button>
            </article>
            );
          })}</div>
        )}
        <datalist id="worker-actions">{authoredActions.map((id) => <option value={id} key={id}>{actionConsequences.has(id) ? `${actionConsequences.get(id)} consequence` : "built-in workflow control"}</option>)}</datalist>
      </section>
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
          <a className="secondary-button" href="#/runs">Inspect runs</a>
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
      <p className="advanced-handoff">Advanced run-event canvas and authoring diagnostics remain in <a href="/operator/#/automations">Operator</a>.</p>
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
            Request {props.pending.requestId}. {props.pending.state === "ready"
              ? "It is approved and ready to finalize."
              : "An independent author must approve it in Inbox first."} Finalization
            replays the exact approved action and returns the one-time secret here.
          </p>
          <button
            className="secondary-button"
            disabled={props.busy || props.pending.state !== "ready"}
            onClick={props.onFinalize}
          >
            Finalize after approval
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
      "Waiting for an Inbox decision",
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
  onRefresh,
}: {
  workflows: WorkflowSummary[];
  stats: Record<string, WorkflowRunStat>;
  onOpen(id: string): void;
  onNew(): void;
  onRefresh(): void;
}) {
  const [steps, setSteps] = useState<Record<string, WorkflowStepDefinition[]>>({});

  // Summaries carry no steps, so the graph has to be read from each detail. A
  // failed read leaves that card without a drawing rather than inventing one.
  useEffect(() => {
    let cancelled = false;
    void Promise.all(workflows.map(async (workflow) => {
      try {
        const detail = await client.workflow(workflow.id);
        const list = (detail.definition?.steps ?? []) as WorkflowStepDefinition[];
        return [workflow.id, Array.isArray(list) ? list : []] as const;
      } catch {
        return [workflow.id, []] as const;
      }
    })).then((entries) => {
      if (cancelled) return;
      setSteps(Object.fromEntries(entries));
    });
    return () => { cancelled = true; };
  }, [workflows]);

  return (
    <>
    <div className="routine-picker-bar">
      <button className="icon-button" aria-label="Refresh workflows" onClick={onRefresh} type="button">↻</button>
    </div>
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
          An empty routine with a chat in it. Ask it to read a run that went well, or say what should happen.
        </span>
      </button>
      {workflows.map((workflow) => {
        const stat = stats[workflow.id];
        const runs = stat?.run_count ?? 0;
        const failed = runs > 0 && (stat?.success_count ?? 0) < runs;
        const tone = runs === 0 ? "unknown" : failed ? "red" : "green";
        const scheduled = Boolean(workflow.schedule);
        const observed = workflow.schedule_state?.observed.status;
        const needsYou = observed === "needs_action";
        return (
          <button
            className="routine-card"
            key={workflow.id}
            onClick={() => onOpen(workflow.id)}
            type="button"
          >
            <span className="routine-thumb">
              <RoutineThumb steps={steps[workflow.id] ?? []} />
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
                <span className="routine-state" data-tone={needsYou ? "needs" : undefined}>
                  {needsYou
                    ? "needs you"
                    : workflow.status === "archived"
                      ? "archived"
                      : scheduled ? "unattended" : "manual"}
                </span>
                <span className="routine-when" data-tone={failed ? "failed" : undefined}>
                  {routineWhen(stat?.last_run_at)}
                </span>
              </span>
            </span>
          </button>
        );
      })}
    </div>
    </>
  );
}
