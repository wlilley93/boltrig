/** DiffView (N19): flat key-path diff of two plain objects. */
// ok/down TEXT tints only, never amber (L4).

interface DiffRow {
  path: string;
  kind: "changed" | "added" | "removed" | "unchanged";
  before?: string;
  after?: string;
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function showValue(v: unknown): string {
  try {
    return JSON.stringify(v) ?? "undefined";
  } catch {
    return String(v);
  }
}

function diffWalk(before: unknown, after: unknown, path: string, out: DiffRow[]): void {
  if (isPlainObject(before) && isPlainObject(after)) {
    const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])];
    for (const k of keys) {
      const p = path ? `${path}.${k}` : k;
      if (!(k in before)) out.push({ path: p, kind: "added", after: showValue(after[k]) });
      else if (!(k in after)) out.push({ path: p, kind: "removed", before: showValue(before[k]) });
      else diffWalk(before[k], after[k], p, out);
    }
    return;
  }
  if (Array.isArray(before) && Array.isArray(after)) {
    const len = Math.max(before.length, after.length);
    for (let i = 0; i < len; i++) {
      const p = `${path}[${i}]`;
      if (i >= before.length) out.push({ path: p, kind: "added", after: showValue(after[i]) });
      else if (i >= after.length) out.push({ path: p, kind: "removed", before: showValue(before[i]) });
      else diffWalk(before[i], after[i], p, out);
    }
    return;
  }
  const b = showValue(before);
  const a = showValue(after);
  out.push(
    b === a
      ? { path, kind: "unchanged", before: b, after: a }
      : { path, kind: "changed", before: b, after: a },
  );
}

export function DiffView({
  before,
  after,
  elideUnchanged,
}: {
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  elideUnchanged?: boolean; // default true
}) {
  const rows: DiffRow[] = [];
  diffWalk(before, after, "", rows);
  const visible = (elideUnchanged ?? true) ? rows.filter((r) => r.kind !== "unchanged") : rows;
  if (visible.length === 0) {
    return <p className="ux-hint">No changes.</p>;
  }
  return (
    <div className="ux-diff">
      {visible.map((r) => (
        <div key={`${r.path}:${r.kind}`} className={`ux-diff__row ux-diff__row--${r.kind}`}>
          <code className="ux-diff__path">{r.path}</code>
          {r.kind === "unchanged" ? (
            <code className="ux-diff__same">{r.after}</code>
          ) : (
            <>
              {r.kind !== "added" && <code className="ux-diff__before">{r.before}</code>}
              {r.kind === "changed" && <span className="ux-diff__arrow">-&gt;</span>}
              {r.kind !== "removed" && <code className="ux-diff__after">{r.after}</code>}
            </>
          )}
        </div>
      ))}
    </div>
  );
}
