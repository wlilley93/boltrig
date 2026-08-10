// Client-side mirror of boltrig/workflows/control_flow.py predicate semantics,
// used by the canvas "Try it" mode. The point of mirroring the engine rather
// than the design mock's nine operators is honesty: a dry walk that used looser
// comparison rules would light paths the real engine will never take. Every
// rule here has a named counterpart in control_flow.py (_compare, eval_predicate,
// _eval_case, select_branch_label); change them together or not at all.

/** The engine's full operator set (control_flow._compare), fail-closed. */
export const BRANCH_OPERATORS = [
  "eq",
  "ne",
  "exists",
  "not_exists",
  "is_null",
  "not_null",
  "empty",
  "not_empty",
  "gt",
  "lt",
  "gte",
  "lte",
  "in",
  "not_in",
  "contains",
  "not_contains",
  "starts_with",
  "ends_with",
] as const;

export type BranchOperator = (typeof BRANCH_OPERATORS)[number];

/**
 * A sample-value lookup for Try it: full `$step.path` reference strings map to
 * the value the user typed. The engine resolves references against real step
 * outputs; here the user supplies the leaf value directly, which is the same
 * information the comparison needs.
 */
export type SampleLookup = (ref: string) => unknown;

/**
 * Mirror of control_flow.resolve_ref's contract at the edge Try it needs:
 * a non-string or non-$ value is a literal; a $ reference resolves through the
 * sample lookup; an unresolved reference is null (fail-open to null, exactly
 * like the engine treats a missing field).
 */
export function resolveSample(value: unknown, lookup: SampleLookup): unknown {
  if (typeof value !== "string" || !value.startsWith("$")) return value;
  const sampled = lookup(value);
  return sampled === undefined ? null : sampled;
}

/**
 * Coerce a typed-in sample string to the type the engine would compare:
 * numbers stay numbers, true/false/null are read as such, everything else is
 * the raw string. The engine never sees strings-for-numbers because real step
 * outputs are typed JSON; this makes hand-typed samples behave the same way.
 */
export function coerceSampleText(text: string): unknown {
  const trimmed = text.trim();
  if (trimmed === "") return "";
  if (trimmed === "true") return true;
  if (trimmed === "false") return false;
  if (trimmed === "null") return null;
  if (!Number.isNaN(Number(trimmed))) return Number(trimmed);
  return text;
}

/** Mirror of control_flow._compare: unknown operators are false (fail-closed). */
export function comparePredicate(
  left: unknown,
  op: string,
  right: unknown,
): boolean {
  switch (op) {
    case "eq":
      return jsonEqual(left, right);
    case "ne":
      return !jsonEqual(left, right);
    case "exists":
      return left !== null && left !== undefined;
    case "not_exists":
    case "is_null":
      return left === null || left === undefined;
    case "not_null":
      return left !== null && left !== undefined;
    case "empty":
      return !truthy(left);
    case "not_empty":
      return truthy(left);
    default:
      break;
  }
  try {
    switch (op) {
      case "gt":
        return ordered(left, right) && (left as number) > (right as number);
      case "lt":
        return ordered(left, right) && (left as number) < (right as number);
      case "gte":
        return ordered(left, right) && (left as number) >= (right as number);
      case "lte":
        return ordered(left, right) && (left as number) <= (right as number);
      case "in":
        return contains(right, left);
      case "not_in":
        return !contains(right, left);
      case "contains":
        return contains(left, right);
      case "not_contains":
        return !contains(left, right);
      case "starts_with":
        return typeof left === "string" && typeof right === "string"
          && left.startsWith(right);
      case "ends_with":
        return typeof left === "string" && typeof right === "string"
          && left.endsWith(right);
      default:
        return false;
    }
  } catch {
    // Python raises TypeError on un-orderable operands and _compare returns
    // False; the ordered() guard above makes this unreachable, kept anyway.
    return false;
  }
}

/**
 * Mirror of control_flow.eval_predicate: no params means an unconditional
 * true branch; a bare {value} form branches on truthiness; otherwise
 * left/op/right through _compare.
 */
export function evalPredicate(
  params: Record<string, unknown>,
  lookup: SampleLookup,
): boolean {
  if (Object.keys(params).length === 0) return true;
  if (!("op" in params)) {
    if ("value" in params) return truthy(resolveSample(params.value, lookup));
    return true;
  }
  const left = resolveSample(params.left, lookup);
  const op = String(params.op ?? "eq");
  const right = resolveSample(params.right, lookup);
  return comparePredicate(left, op, right);
}

/**
 * Mirror of control_flow.select_branch_label: legacy predicates label
 * "true"/"false"; a cases[] list labels with the first matching case (a case
 * without conditions matches unconditionally; a case without a usable string
 * label never matches), else default_label or "false".
 */
export function selectBranchLabel(
  params: Record<string, unknown>,
  lookup: SampleLookup,
): string {
  const cases = params.cases;
  if (Array.isArray(cases)) {
    for (const candidate of cases) {
      if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) continue;
      const record = candidate as Record<string, unknown>;
      const label = record.label;
      if (typeof label !== "string" || !label) continue;
      if (evalCase(record, lookup)) return label;
    }
    const fallback = params.default_label;
    return typeof fallback === "string" && fallback ? fallback : "false";
  }
  return evalPredicate(params, lookup) ? "true" : "false";
}

/** Collect every `$step.path` reference string used by a branch predicate. */
export function predicateSampleRefs(params: Record<string, unknown>): string[] {
  const refs: string[] = [];
  const push = (value: unknown) => {
    if (typeof value === "string" && value.startsWith("$") && value.length > 1) {
      if (!refs.includes(value)) refs.push(value);
    }
  };
  push(params.left);
  push(params.right);
  push(params.value);
  if (Array.isArray(params.cases)) {
    for (const candidate of params.cases) {
      if (!candidate || typeof candidate !== "object") continue;
      const conditions = (candidate as Record<string, unknown>).conditions;
      if (!Array.isArray(conditions)) continue;
      for (const condition of conditions) {
        if (!condition || typeof condition !== "object") continue;
        push((condition as Record<string, unknown>).left);
        push((condition as Record<string, unknown>).right);
      }
    }
  }
  return refs;
}

/**
 * The structured left/op/right shape the inspector's predicate editor can
 * round-trip without loss. Multi-case, bare-value, and any predicate carrying
 * extra keys stay in the raw JSON editor so the editor never clobbers a shape
 * it does not fully represent.
 */
export interface SimplePredicate {
  left: string;
  op: string;
  right: string;
}

export function simplePredicateFromParams(
  params: Record<string, unknown>,
): SimplePredicate | null {
  const keys = Object.keys(params);
  if (!keys.every((key) => key === "left" || key === "op" || key === "right")) {
    return null;
  }
  const scalar = (value: unknown): string | null => {
    if (value === undefined) return "";
    if (typeof value === "string") return value;
    if (typeof value === "number" || typeof value === "boolean") return String(value);
    return null;
  };
  const left = scalar(params.left);
  const right = scalar(params.right);
  const op = params.op === undefined ? "eq" : params.op;
  if (left === null || right === null || typeof op !== "string") return null;
  return { left, op, right };
}

export function simplePredicateToParams(
  predicate: SimplePredicate,
): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  if (predicate.left !== "") params.left = literalOrRef(predicate.left);
  params.op = predicate.op;
  if (predicate.right !== "") params.right = literalOrRef(predicate.right);
  return params;
}

// --- internals --------------------------------------------------------------

function evalCase(record: Record<string, unknown>, lookup: SampleLookup): boolean {
  const conditions = record.conditions;
  if (conditions === undefined || conditions === null
    || (Array.isArray(conditions) && conditions.length === 0)) {
    return true;
  }
  if (!Array.isArray(conditions)) return false;
  const verdicts: boolean[] = [];
  for (const condition of conditions) {
    if (!condition || typeof condition !== "object" || Array.isArray(condition)) {
      return false;
    }
    const cond = condition as Record<string, unknown>;
    verdicts.push(comparePredicate(
      resolveSample(cond.left, lookup),
      String(cond.op ?? "eq"),
      resolveSample(cond.right, lookup),
    ));
  }
  const joiner = String(record.logical_operator ?? "and");
  return joiner === "or" ? verdicts.some(Boolean) : verdicts.every(Boolean);
}

/** Python truthiness for the values a predicate can see. */
function truthy(value: unknown): boolean {
  if (value === null || value === undefined || value === false) return false;
  if (value === 0 || value === "") return false;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "object") return Object.keys(value as object).length > 0;
  return Boolean(value);
}

/** Python raises on cross-type ordering; mirror by failing closed. */
function ordered(left: unknown, right: unknown): boolean {
  return (typeof left === "number" && typeof right === "number")
    || (typeof left === "string" && typeof right === "string");
}

/** Python `x in y` over the shapes a predicate can see. */
function contains(haystack: unknown, needle: unknown): boolean {
  if (typeof haystack === "string") return haystack.includes(String(needle));
  if (Array.isArray(haystack)) {
    return haystack.some((item) => jsonEqual(item, needle));
  }
  if (haystack && typeof haystack === "object") {
    return Object.prototype.hasOwnProperty.call(haystack, String(needle));
  }
  return false;
}

function jsonEqual(left: unknown, right: unknown): boolean {
  if (left === right) return true;
  if (typeof left !== typeof right) return false;
  if (left === null || right === null) return false;
  if (typeof left === "object") {
    return JSON.stringify(left) === JSON.stringify(right);
  }
  return false;
}

/** Keep a typed literal typed when serializing the structured editor back. */
function literalOrRef(text: string): unknown {
  if (text.startsWith("$")) return text;
  return coerceSampleText(text);
}
