import type { PropSpec } from "./schemaTypes";

// How deep the typed inset-group / row-card recursion goes before a nested object
// falls back to the per-field JSON escape hatch. One top-level group plus three
// more levels covers every shipped admin section (e.g. tier2[] -> budget, or
// runtimes.pi -> sandbox) without risking an unbounded recurse on a pathological
// schema.
export const MAX_INSET_DEPTH = 4;

export function specOf(schema: unknown): { props: Record<string, PropSpec>; required: Set<string> } {
  const s = (schema ?? {}) as { properties?: Record<string, PropSpec>; required?: string[] };
  return { props: s.properties ?? {}, required: new Set(s.required ?? []) };
}

export function skeletonFor(spec: PropSpec): unknown {
  const t = spec.type;
  if (t === "number" || t === "integer") return 0;
  if (t === "boolean") return false;
  if (t === "array") return [];
  if (t === "object") return {};
  return "";
}

// P12: seed a params object so no field opens blank; the schema's own default
// wins over the type's zero-cost skeleton (mirroring the kernel's defaults).
export function schemaDefaults(schema: unknown): Record<string, unknown> {
  const { props } = specOf(schema);
  const out: Record<string, unknown> = {};
  for (const [k, spec] of Object.entries(props)) {
    out[k] = spec.default !== undefined ? spec.default : skeletonFor(spec);
  }
  return out;
}

export function isLongText(key: string, spec: PropSpec): boolean {
  if (spec.format === "textarea") return true;
  return /prompt|body|description|notes|message|question/i.test(`${key} ${spec.description ?? ""}`);
}
