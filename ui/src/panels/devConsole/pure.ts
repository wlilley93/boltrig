// Pure helpers for the Dev console: schema manipulation, JSON safety, and
// run-id extraction. No React, no HTTP - just value transformations.

// Safely parse the params JSON into an object for the schema form (an in-progress
// edit may be invalid; the form just sees {} until it is valid again).
export function safeObj(text: string): Record<string, unknown> {
  try {
    const v = JSON.parse(text || "{}");
    return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

// Build a starter params object from a verb's JSON-Schema input_schema, so the
// box is never blank: each declared property gets a typed placeholder.
export function skeletonFromSchema(schema: unknown): string {
  if (!schema || typeof schema !== "object") return "{}";
  const props = (schema as { properties?: Record<string, { type?: string }> }).properties;
  if (!props || typeof props !== "object") return "{}";
  const obj: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(props)) {
    const t = v?.type;
    obj[k] =
      t === "number" || t === "integer"
        ? 0
        : t === "boolean"
          ? false
          : t === "array"
            ? []
            : t === "object"
              ? {}
              : "";
  }
  return JSON.stringify(obj, null, 2);
}

export function schemaKeys(schema: unknown): { required: string[]; optional: string[] } {
  const out = { required: [] as string[], optional: [] as string[] };
  if (!schema || typeof schema !== "object") return out;
  const s = schema as { properties?: Record<string, unknown>; required?: string[] };
  const req = new Set(s.required ?? []);
  for (const k of Object.keys(s.properties ?? {})) {
    (req.has(k) ? out.required : out.optional).push(k);
  }
  return out;
}

// Read a run_id off an arbitrary result body without widening the typed unions:
// the kernel may carry it at the top level or inside `output`.
export function pluckRunId(value: unknown): string | undefined {
  if (value && typeof value === "object" && "run_id" in value) {
    const id = (value as { run_id?: unknown }).run_id;
    if (typeof id === "string" && id) return id;
  }
  return undefined;
}

export function runIdOf(value: unknown): string | undefined {
  const direct = pluckRunId(value);
  if (direct) return direct;
  if (value && typeof value === "object" && "output" in value) {
    return pluckRunId((value as { output?: unknown }).output);
  }
  return undefined;
}
