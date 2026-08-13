import type {
  Artifact,
  ChatAttachment,
  FamiliarGenotype,
  IntegrationCatalogueEntry,
  NormalizedTurn,
  StepEntry,
  SubagentEntry,
  ToolEntry,
} from "@wlilley93/boltrig-web-sdk";

/**
 * Deliberately small projection for the task inspector. Tool arguments,
 * results, attachment bytes, artifact provenance and integration setup copy do
 * not belong here. Keeping those fields out of the type makes the compact rail
 * a summary surface rather than a second exact-details renderer.
 */
export type TaskInspectorStatus =
  | "running"
  | "waiting"
  | "done"
  | "paused"
  | "degraded"
  | "skipped"
  | "failed"
  | "unknown";

export interface TaskInspectorOutput {
  id: string;
  name: string;
  mediaType: string;
  revision: number;
  size: number;
}

export interface TaskInspectorSubagent {
  id: string;
  name: string;
  status: TaskInspectorStatus;
  familiarGenotype?: FamiliarGenotype | null;
}

export type TaskInspectorActivityKind =
  | "background"
  | "computer"
  | "tool"
  | "step"
  | "approval"
  | "question";

export interface TaskInspectorActivity {
  id: string;
  /** A registry verb or bounded system label; never a command or args value. */
  label: string;
  status: TaskInspectorStatus;
  kind: TaskInspectorActivityKind;
}

export type TaskInspectorSource =
  | {
    id: string;
    kind: "integration";
    name: string;
    integrationId: string;
  }
  | {
    id: string;
    kind: "attachment";
    name: string;
    attachmentIndex: number;
    mediaType: string;
    size?: number;
  };

export interface TaskInspectorViewModel {
  outputs: TaskInspectorOutput[];
  subagents: TaskInspectorSubagent[];
  backgroundProcesses: TaskInspectorActivity[];
  computerUse: TaskInspectorActivity[];
  sources: TaskInspectorSource[];
  runActivity: TaskInspectorActivity[];
}

export interface TaskInspectorContracts {
  artifacts?: readonly Artifact[];
  integrationSources?: readonly IntegrationCatalogueEntry[];
  sources?: readonly ChatAttachment[];
  turn: NormalizedTurn;
}

export function buildTaskInspectorModel({
  artifacts = [],
  integrationSources = [],
  sources = [],
  turn,
}: TaskInspectorContracts): TaskInspectorViewModel {
  const backgroundProcesses: TaskInspectorActivity[] = [];
  const computerUse: TaskInspectorActivity[] = [];

  for (const tool of turn.tools) {
    const surface = taskInspectorToolSurface(tool.verb);
    if (surface === "background") backgroundProcesses.push(activityFromTool(tool, surface));
    if (surface === "computer") computerUse.push(activityFromTool(tool, surface));
  }

  return {
    outputs: artifacts.map((artifact) => ({
      id: artifact.id,
      name: artifact.name,
      mediaType: artifact.media_type,
      revision: artifact.revision,
      size: artifact.size,
    })),
    subagents: turn.subagents.map((subagent, index) => subagentView(subagent, index, turn.ended)),
    backgroundProcesses,
    computerUse,
    sources: [
      ...integrationSources.map((source) => ({
        id: `integration:${source.id}`,
        kind: "integration" as const,
        name: source.label,
        integrationId: source.id,
      })),
      ...sources.map((source, index) => ({
        // The index distinguishes same-name revisions without retaining the
        // base64 payload that ChatView uses for its durable dedupe identity.
        id: `attachment:${index}:${source.name}`,
        kind: "attachment" as const,
        name: source.name,
        attachmentIndex: index,
        mediaType: source.media_type,
        size: source.size,
      })),
    ],
    runActivity: runActivityFromTurn(turn),
  };
}

export function hasTaskInspectorContent(model: TaskInspectorViewModel): boolean {
  return model.outputs.length > 0
    || model.subagents.length > 0
    || model.backgroundProcesses.length > 0
    || model.computerUse.length > 0
    || model.sources.length > 0
    || model.runActivity.length > 0;
}

export function taskInspectorToolSurface(verb: string): "background" | "computer" | null {
  const normalized = verb.trim().toLowerCase().replaceAll("-", "_");
  if (
    normalized === "computer_use"
    || normalized.startsWith("computer.")
    || normalized.startsWith("computer_use.")
  ) return "computer";
  if (
    normalized === "background_process"
    || normalized.startsWith("background.")
    || normalized.startsWith("background_process.")
    || normalized.startsWith("process.background.")
  ) return "background";
  return null;
}

export function taskInspectorStatus(status: string | undefined): TaskInspectorStatus {
  const normalized = status?.trim().toLowerCase().replaceAll("-", "_") ?? "";
  if (["pending", "running", "in_flight", "working"].includes(normalized)) return "running";
  if (["pending_human", "awaiting_human", "waiting", "held"].includes(normalized)) {
    return "waiting";
  }
  if (["ok", "done", "complete", "completed", "success", "succeeded"].includes(normalized)) {
    return "done";
  }
  if (normalized === "paused") return "paused";
  if (normalized === "degraded") return "degraded";
  if (normalized === "skipped") return "skipped";
  if (["", "unknown"].includes(normalized)) return "unknown";
  // Kernel reason strings (grant_missing, rate_limited, schema_invalid, ...)
  // are terminal non-successes even when they do not literally say "error".
  return "failed";
}

export function taskInspectorLabelFromVerb(verb: string): string {
  const words = verb
    .trim()
    .split(/[._\-\s]+/u)
    .filter(Boolean)
    .map((word) => word.toLowerCase());
  if (words.length === 0) return "Tool activity";
  const label = words.join(" ");
  return `${label.slice(0, 1).toUpperCase()}${label.slice(1)}`;
}

function activityFromTool(
  tool: ToolEntry,
  kind: Extract<TaskInspectorActivityKind, "background" | "computer" | "tool">,
): TaskInspectorActivity {
  return {
    id: tool.callId ?? tool.key,
    kind,
    label: taskInspectorLabelFromVerb(tool.verb),
    status: taskInspectorStatus(tool.status),
  };
}

function activityFromStep(step: StepEntry): TaskInspectorActivity {
  return {
    id: step.stepId,
    kind: "step",
    // Step actions are already the bounded, user-visible workflow labels in
    // the transcript contract. No workflow input or result is projected.
    label: step.action,
    status: taskInspectorStatus(step.status),
  };
}

function subagentView(
  subagent: SubagentEntry,
  index: number,
  turnEnded: boolean,
): TaskInspectorSubagent {
  const status = subagent.status === undefined && !turnEnded
    ? "running"
    : taskInspectorStatus(subagent.status);
  return {
    id: subagent.childRunId || subagent.key,
    // Tasks can contain user material. The compact rail uses only capability
    // identity and falls back to a neutral ordinal rather than copying a task.
    name: subagent.name ?? subagent.role ?? `Subagent ${index + 1}`,
    status,
    familiarGenotype: subagent.familiarGenotype,
  };
}

function runActivityFromTurn(turn: NormalizedTurn): TaskInspectorActivity[] {
  const items: TaskInspectorActivity[] = [];
  const seen = new Set<string>();

  const add = (item: TaskInspectorActivity) => {
    const key = `${item.kind}:${item.id}`;
    if (seen.has(key)) return;
    seen.add(key);
    items.push(item);
  };

  for (const entry of turn.timeline) {
    if (entry.kind === "tool" && taskInspectorToolSurface(entry.entry.verb) === null) {
      add(activityFromTool(entry.entry, "tool"));
    } else if (entry.kind === "steps") {
      entry.entries.forEach((step) => add(activityFromStep(step)));
    } else if (entry.kind === "hitl") {
      add({
        id: entry.entry.hitlRequestId,
        kind: "approval",
        label: "Approval requested",
        status: "waiting",
      });
    } else if (entry.kind === "question") {
      add({
        id: entry.entry.questionId,
        kind: "question",
        label: "Question asked",
        status: "waiting",
      });
    }
  }

  // Older persisted frames can populate the normalized arrays without the
  // newer ordered timeline. The same narrow projection keeps their rail useful.
  if (turn.timeline.length === 0) {
    turn.tools
      .filter((tool) => taskInspectorToolSurface(tool.verb) === null)
      .forEach((tool) => add(activityFromTool(tool, "tool")));
    turn.steps.forEach((step) => add(activityFromStep(step)));
    turn.hitls.forEach((hitl) => add({
      id: hitl.hitlRequestId,
      kind: "approval",
      label: "Approval requested",
      status: "waiting",
    }));
    turn.questions.forEach((question) => add({
      id: question.questionId,
      kind: "question",
      label: "Question asked",
      status: "waiting",
    }));
  }

  return items;
}
