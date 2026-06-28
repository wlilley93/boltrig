// Small helpers shared by the Round Three panels: JSON form parsing, pretty
// rendering, comma-list conversion, and a couple of tiny presentational pieces.
// Keeping these here keeps each panel focused on its own flow.

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
