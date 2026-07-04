import { useMemo, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

import { grantMatches, scopeMatches, type ScopeVerb } from "./scopeMatches";

export interface UseScopeBuilderArgs {
  value: string[];
  onChange: (v: string[]) => void;
  verbs: ScopeVerb[];
}

export interface UseScopeBuilderResult {
  query: string;
  setQuery: Dispatch<SetStateAction<string>>;
  openNouns: Record<string, boolean>;
  setOpenNouns: Dispatch<SetStateAction<Record<string, boolean>>>;
  matched: ScopeVerb[];
  matchedHigh: number;
  deadPatterns: string[];
  nouns: [string, ScopeVerb[]][];
  q: string;
  add: (p: string) => void;
}

export function useScopeBuilder({ value, onChange, verbs }: UseScopeBuilderArgs): UseScopeBuilderResult {
  const [query, setQuery] = useState("");
  const [openNouns, setOpenNouns] = useState<Record<string, boolean>>({});

  const matched = useMemo(() => scopeMatches(value, verbs), [value, verbs]);
  const matchedHigh = matched.filter((v) => v.consequence === "high").length;
  const deadPatterns = useMemo(
    () => value.filter((p) => !verbs.some((v) => grantMatches(p, v.id))),
    [value, verbs],
  );

  const nouns = useMemo(() => {
    const by = new Map<string, ScopeVerb[]>();
    for (const v of verbs) {
      const list = by.get(v.noun);
      if (list) list.push(v);
      else by.set(v.noun, [v]);
    }
    return [...by.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [verbs]);

  const q = query.trim().toLowerCase();

  const add = (p: string) => {
    if (!value.includes(p)) onChange([...value, p]);
  };

  return {
    query,
    setQuery,
    openNouns,
    setOpenNouns,
    matched,
    matchedHigh,
    deadPatterns,
    nouns,
    q,
    add,
  };
}
