import type { ReadinessCheck } from "@wlilley93/boltrig-web-sdk";

import type { Tone } from "./rowKit";

const CHECK_COPY: Record<string, { title: string; sub: string }> = {
  postgres: { title: "Where everything is kept", sub: "The store that holds runs, approvals and the record" },
  redis: { title: "Coordination between parts", sub: "Coordinates background work" },
  migration: { title: "The storage schema", sub: "Storage is on the required version" },
  control_plane: { title: "Accounts and policy", sub: "Who may do what, decided server-side" },
  stack_tools: { title: "Acting in your systems", sub: "The tools boltrig uses to do real work" },
  hatchet: { title: "Background work", sub: "The runner for long and queued work" },
  model_gateway: { title: "Reaching the models", sub: "The gateway that does the thinking" },
  codex_runtime: { title: "Cloud agent runtime", sub: "Runs browser-based coding agents when its safety checks are complete" },
  password_reset_delivery: { title: "Password reset delivery", sub: "How a reset actually reaches a person" },
  hitl_expiry_janitor: { title: "Expired decisions", sub: "Clears approvals and questions after they time out" },
  retention_janitor: { title: "Retention cleanup", sub: "Removes data after its configured retention period" },
  distillation_janitor: { title: "Memory distillation", sub: "Turns completed work into reusable memory when enabled" },
  anchor_janitor: { title: "Memory anchors", sub: "Refreshes durable memory anchors when enabled" },
  workflow_scheduler_janitor: { title: "Routine scheduling", sub: "Checks for routines that are due to run" },
  pump_janitor: { title: "Background processing", sub: "Advances queued background work" },
  reflection_janitor: { title: "Reflection", sub: "Reviews completed work when reflection is enabled" },
};

export function plainCheckCopy(name: string, check: ReadinessCheck) {
  const known = CHECK_COPY[name];
  if (known) return known;
  const title = name.split("_").filter(Boolean)
    .map((part) => part[0]?.toUpperCase() + part.slice(1)).join(" ") || "Service check";
  return { title, sub: check.required ? "Required service check" : "Optional service check" };
}

function checkTone(check: ReadinessCheck): { tone: Tone; state: string } {
  if (check.status === "ready" || check.status === "ok") return { tone: "green", state: "fine" };
  if (check.status === "disabled") return { tone: "unknown", state: "switched off" };
  if (check.required) return { tone: "red", state: "not working" };
  return { tone: "amber", state: "struggling" };
}

export function readinessTone(name: string, check: ReadinessCheck): { tone: Tone; state: string } {
  if (name === "codex_runtime" && check.status === "test_only") {
    return { tone: "unknown", state: "development only" };
  }
  if (name.endsWith("_janitor") && check.reason === "attempt_evidence_not_observed") {
    return { tone: "unknown", state: "not observed" };
  }
  return checkTone(check);
}
