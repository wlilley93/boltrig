export interface ScopeVerb {
  id: string;
  noun: string;
  consequence?: string;
}

// Grant token semantics: "*" matches everything; "noun.*" (any trailing "*")
// is a prefix pattern; anything else is an exact verb id.
export function grantMatches(pattern: string, verbId: string): boolean {
  if (pattern === "*") return true;
  if (pattern.endsWith("*")) return verbId.startsWith(pattern.slice(0, -1));
  return pattern === verbId;
}

export function scopeMatches(patterns: string[], verbs: ScopeVerb[]): ScopeVerb[] {
  return verbs.filter((v) => patterns.some((p) => grantMatches(p, v.id)));
}
