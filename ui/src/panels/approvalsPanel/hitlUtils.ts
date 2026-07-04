export function renderContext(context: unknown): string | null {
  if (context === null || context === undefined) return null;
  if (typeof context === "string") return context;
  try {
    return JSON.stringify(context, null, 2);
  } catch {
    return String(context);
  }
}

export function runFromContext(context: unknown): string | null {
  if (!context || typeof context !== "object") return null;
  const obj = context as Record<string, unknown>;
  const candidate = obj.run_id ?? obj.run;
  return typeof candidate === "string" && candidate ? candidate : null;
}

// Pull the faithful server reason out of a thrown ApiError (its body carries a
// reason on a 403/409) rather than leaking "POST ... -> 403".
export function reasonOf(err: unknown): string {
  if (err && typeof err === "object") {
    const body = (err as { body?: unknown }).body;
    if (body && typeof body === "object") {
      const r = (body as { reason?: unknown }).reason;
      if (typeof r === "string" && r) return r;
    }
  }
  return err instanceof Error ? err.message : String(err);
}

// "approve"-like options read as the primary, weighted action; "reject"-like as
// a neutral decline. Everything else is a neutral button.
export function optionClass(opt: string): string {
  const o = opt.toLowerCase();
  if (o === "approve" || o === "yes" || o === "allow") return "btn btn--primary";
  if (o === "reject" || o === "no" || o === "deny") return "btn btn--danger";
  return "btn";
}
