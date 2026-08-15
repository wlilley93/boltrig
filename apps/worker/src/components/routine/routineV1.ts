import type {
  RoutineDefinition,
  UpsertWorkflowRequest,
  WorkflowRunDescriptor,
  WorkflowSummary,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import {
  governedRouteRefusal,
  type GovernedResult,
} from "../ExactApprovalFinalizer";

export type Companion = "familiar" | "jarvis";
export type Timing = "manual" | "daily" | "weekdays";

export interface RoutineDraft {
  id: string;
  name: string;
  goal: string;
  companion: Companion;
  notifyCompletion: boolean;
}

export interface RoutineScreenState {
  workflows: WorkflowSummary[];
  loadState: "loading" | "ready" | "unavailable";
  selectedId: string | null;
  draft: RoutineDraft;
  timing: Timing;
  time: string;
  timezone: string;
  hasSchedule: boolean;
  dirty: boolean;
  busy: boolean;
  message: string;
}

export type RoutineMutation =
  | { kind: "save"; body: UpsertWorkflowRequest }
  | { kind: "run"; workflowId: string }
  | { kind: "schedule"; workflowId: string; cron: string; timezone: string }
  | { kind: "unschedule"; workflowId: string };

export interface RoutineMutationResult extends GovernedResult {
  value?: unknown;
}

export const EMPTY_DRAFT: RoutineDraft = {
  id: "",
  name: "",
  goal: "",
  companion: "familiar",
  notifyCompletion: true,
};

export function initialRoutineState(): RoutineScreenState {
  return {
    workflows: [],
    loadState: "loading",
    selectedId: null,
    draft: EMPTY_DRAFT,
    timing: "manual",
    time: "09:00",
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
    hasSchedule: false,
    dirty: false,
    busy: false,
    message: "",
  };
}

export async function performRoutineMutation(
  input: RoutineMutation,
  approvalId?: string,
): Promise<RoutineMutationResult> {
  if (input.kind === "save") {
    const result = await client.upsertWorkflow(input.body, approvalId);
    return { ...result, value: result };
  }
  if (input.kind === "run") return runRoutine(input.workflowId, approvalId);
  if (input.kind === "schedule") {
    const result = await client.scheduleWorkflow(input.workflowId, {
      cron: input.cron,
      timezone: input.timezone,
    }, approvalId);
    return { ...result, value: result };
  }
  const result = await client.unscheduleWorkflow(input.workflowId, approvalId);
  return { ...result, value: result };
}

async function runRoutine(workflowId: string, approvalId?: string) {
  const result = await client.triggerWorkflow(workflowId, {}, approvalId);
  if (result.status === "pending_human") {
    return result as RoutineMutationResult;
  }
  const refusal = governedRouteRefusal(result);
  if (refusal) return refusal;
  const run = result as WorkflowRunDescriptor;
  if (!run.run_id || !run.conversation_id) {
    return { status: "error", reason: run.error ?? "routine_run_not_queued" };
  }
  return { status: "ok", value: run } satisfies RoutineMutationResult;
}

export function requestFor(draft: RoutineDraft): UpsertWorkflowRequest {
  return {
    id: draft.id,
    version: "1.0.0",
    definition: {
      steps: [],
      _boltrig_routine: {
        version: 1,
        name: draft.name.trim(),
        goal: draft.goal.trim(),
        companion_id: draft.companion,
        notify: { completion: draft.notifyCompletion },
      },
    },
    intent_tags: ["routine"],
  };
}

export function scheduleFor(timing: Timing, time: string, timezone: string) {
  if (timing === "manual") return null;
  const [hour, minute] = time.split(":").map(Number);
  if (
    !Number.isInteger(hour)
    || !Number.isInteger(minute)
    || hour! < 0
    || hour! > 23
    || minute! < 0
    || minute! > 59
  ) return null;
  return {
    cron: `${minute} ${hour} * * ${timing === "weekdays" ? "1-5" : "*"}`,
    timezone,
  };
}

export function timingFrom(cron?: string): { timing: Timing; time: string } {
  const match = /^(\d{1,2}) (\d{1,2}) \* \* (\*|1-5)$/.exec(cron ?? "");
  if (!match) return { timing: "manual", time: "09:00" };
  return {
    timing: match[3] === "1-5" ? "weekdays" : "daily",
    time: `${match[2].padStart(2, "0")}:${match[1].padStart(2, "0")}`,
  };
}

export function scheduleLabel(cron?: string): string {
  const parsed = timingFrom(cron);
  if (!cron) return "Manual";
  if (parsed.timing === "weekdays") return `Weekdays · ${parsed.time}`;
  return parsed.timing === "daily" ? `Daily · ${parsed.time}` : "Scheduled";
}

export function nameOf(id: Companion): string {
  return id === "jarvis" ? "Jarvis" : "Familiar";
}

export function isRoutine(value: unknown): value is RoutineDefinition {
  if (!value || typeof value !== "object") return false;
  const item = value as Partial<RoutineDefinition>;
  return item.version === 1
    && typeof item.name === "string"
    && typeof item.goal === "string"
    && (item.companion_id === "familiar" || item.companion_id === "jarvis");
}

export function workflowRun(result: RoutineMutationResult) {
  return result.value as WorkflowRunDescriptor | undefined;
}

export function sameJson(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}
