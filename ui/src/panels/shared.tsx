// Small helpers shared by the Round Three panels: JSON form parsing, pretty
// rendering, comma-list conversion, and a couple of tiny presentational pieces.
// Keeping these here keeps each panel focused on its own flow.

import { ApiError } from "../api/client";
import { openRun } from "../router";

export function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

// The faithful server reason for a thrown call: an ApiError carries the kernel's
// {reason} in its body on a 403/409, which is more useful than "POST ... -> 403".
export function apiReason(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.body && typeof err.body === "object" && "reason" in err.body) {
      const r = (err.body as { reason: unknown }).reason;
      if (typeof r === "string" && r) return r;
    }
    if (err.status === 403) return "You don't have access to this.";
    if (err.status === 0) return "Can't reach the server - check your connection.";
  }
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

// The kernel wraps delegated conversation turns in a safety envelope before they
// reach a sub-agent, e.g. `User: <untrusted kind="conversation_turn"
// source="user">Hello</untrusted>\nrun: bf97e4e4...`. That raw form must never
// reach the DOM. This unwraps the inner text the user actually sent and drops
// the role prefix, provenance line and any other angle-bracket tags, so a
// displayed task / label reads as plain text again.
export function cleanTaskText(raw: string | undefined | null): string {
  if (!raw) return "";
  let s = String(raw);
  s = s.replace(/<untrusted\b[^>]*>([\s\S]*?)<\/untrusted>/gi, "$1");
  s = s.replace(/<\/?[a-z_][\w:-]*\b[^>]*>/gi, "");
  s = s.replace(/^\s*run:\s*[0-9a-f]{6,}\s*$/gim, "");
  s = s.replace(/^\s*(user|assistant|system):\s*/gim, "");
  return s.trim();
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
