// Small helpers shared by the Round Three panels: JSON form parsing, pretty
// rendering, comma-list conversion, and a couple of tiny presentational pieces.
// Keeping these here keeps each panel focused on its own flow.

import { openRun } from "../router";

export function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function prettyJson(value: unknown): string {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

// Parse JSON from a textarea, returning the fallback for empty input and
// throwing a friendly "invalid JSON" so a form can surface it rather than crash.
export function parseJson<T>(text: string, fallback: T): T {
  const t = text.trim();
  if (!t) return fallback;
  try {
    return JSON.parse(t) as T;
  } catch {
    throw new Error("invalid JSON");
  }
}

// "a, b , c" -> ["a", "b", "c"]; trims and drops empties.
export function csvToList(text: string): string[] {
  return text
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

export function listToCsv(items: ReadonlyArray<string> | undefined): string {
  return (items ?? []).join(", ");
}

// "all" | string[] -> a readable scope label for the insight copy.
export function scopeLabel(scope: string[] | string | undefined): string {
  if (scope === undefined) return "unknown";
  if (typeof scope === "string") return scope;
  return scope.length > 0 ? scope.join(", ") : "none";
}

export function CodeBlock({ value }: { value: unknown }) {
  return <pre className="codeblock">{prettyJson(value)}</pre>;
}

// A run id rendered as a handle that raises the global Run drawer (router.openRun).
// Used wherever a panel surfaces a run_id so every run is one click from its
// live events, execution tree and cost.
export function RunLink({ runId, label }: { runId: string; label?: string }) {
  return (
    <button
      className="run-handle"
      title="Open run drawer"
      onClick={() => openRun(runId)}
    >
      <code>{label ?? runId}</code>
    </button>
  );
}

// Map an overall workflow-run status to an existing badge colour modifier. Used
// by both the form-based Execute view and the Canvas Run view.
export function runBadgeClass(status: string): string {
  switch (status) {
    case "completed":
      return "badge--ok";
    case "failed":
      return "badge--down";
    case "paused":
      return "badge--degraded";
    default:
      return "badge--unknown";
  }
}

// Map a per-step run status to an existing badge colour modifier.
export function stepBadgeClass(status: string): string {
  switch (status) {
    case "ok":
      return "badge--ok";
    case "failed":
    case "error":
      return "badge--down";
    case "paused":
      return "badge--degraded";
    default:
      // skipped (and anything unrecognised) reads as neutral.
      return "badge--unknown";
  }
}

// Renders a grant list as monospace chips (the no-escalation evidence shown by
// test-spawn, eval and personal-agent invoke).
export function GrantList({ grants }: { grants?: string[] }) {
  if (!grants || grants.length === 0) {
    return <span className="muted">none</span>;
  }
  return (
    <span className="kv">
      {grants.map((g) => (
        <code className="tag" key={g}>
          {g}
        </code>
      ))}
    </span>
  );
}
