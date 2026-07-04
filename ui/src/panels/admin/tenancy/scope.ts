import type { VerbInfo } from "@/api/types";
import type { ScopeVerb } from "@/panels/uxForm";

// A user's permission scope (manifest role-mapping shape): an all-access flag,
// visible departments, and the verb dimension expressed as noun/verb grants.
// ScopeBuilder owns the verb dimension as a flat pattern list; these helpers
// translate the dict <-> patterns while preserving departments and any keys the
// UI does not surface (fail-safe: an unknown scope key is never dropped).
const SCOPE_VERB_KEYS: ReadonlySet<string> = new Set(["all", "nouns", "verbs"]);

export function asStringList(v: unknown): string[] {
  return Array.isArray(v) ? v.map((x) => String(x)) : [];
}

export function scopeToPatterns(scope: Record<string, unknown>): string[] {
  if (scope.all) return ["*"];
  const nouns = asStringList(scope.nouns).map((n) => `${n}.*`);
  return [...nouns, ...asStringList(scope.verbs)];
}

// The verb-dimension part of a scope dict, derived from the pattern list.
export function patternsToScopeVerbPart(
  patterns: string[],
): Record<string, unknown> {
  if (patterns.includes("*")) return { all: true };
  const nouns: string[] = [];
  const verbs: string[] = [];
  for (const p of patterns) {
    if (p === "*") continue;
    if (p.endsWith(".*")) nouns.push(p.slice(0, -2));
    else if (p.endsWith("*")) nouns.push(p.slice(0, -1));
    else verbs.push(p);
  }
  const part: Record<string, unknown> = {};
  if (nouns.length > 0) part.nouns = nouns;
  if (verbs.length > 0) part.verbs = verbs;
  return part;
}

// VerbInfo registry -> ScopeBuilder's verb shape (id + noun + consequence).
export function toScopeVerbs(verbs: VerbInfo[]): ScopeVerb[] {
  return verbs.map((v) => ({
    id: v.id,
    noun: v.noun,
    consequence: typeof v.consequence === "string" ? v.consequence : undefined,
  }));
}

// Preserve any scope keys the editor does not surface (never drop them), and
// rewrite only the verb dimension + departments from the controls.
export function buildScopePatch(
  original: Record<string, unknown>,
  departments: string[],
  patterns: string[],
): Record<string, unknown> {
  const scope: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(original)) {
    if (k === "departments" || SCOPE_VERB_KEYS.has(k)) continue;
    scope[k] = v;
  }
  if (departments.length > 0) scope.departments = departments;
  Object.assign(scope, patternsToScopeVerbPart(patterns));
  return scope;
}
