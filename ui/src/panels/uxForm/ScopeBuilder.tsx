import type { ReactNode } from "react";

import { ScopeBuilderChips } from "./ScopeBuilderChips";
import { ScopeBuilderNoun } from "./ScopeBuilderNoun";
import { ScopeBuilderPresets } from "./ScopeBuilderPresets";
import { ScopeBuilderPreview } from "./ScopeBuilderPreview";
import { useScopeBuilder } from "./useScopeBuilder";
import { type ScopeVerb } from "./scopeMatches";

// --- N5 ScopeBuilder: grant/scope patterns with live match preview (P7). ----
// One value shape serves skill tool_grants, PAT scopes, supported_skills and
// eval forbidden_grants: a string[] of tokens and patterns. The verbs prop is
// the caller-scoped registry (no fetching inside); presets are client-side
// sugar (the value stays the pattern list); warn is the dropped-patterns
// slot. Consequence-high verbs carry the glossary badge (L4: amber only for
// kernel governance).
export function ScopeBuilder({
  value,
  onChange,
  verbs,
  presets,
  warn,
  disabled = false,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  verbs: ScopeVerb[];
  presets?: { label: string; value: string[] }[];
  warn?: ReactNode;
  disabled?: boolean;
}) {
  const { query, setQuery, openNouns, setOpenNouns, matched, matchedHigh, deadPatterns, nouns, q, add } =
    useScopeBuilder({ value, onChange, verbs });

  return (
    <div className="ux-scope">
      <ScopeBuilderPresets presets={presets} disabled={disabled} onChange={onChange} />
      <ScopeBuilderChips value={value} deadPatterns={deadPatterns} disabled={disabled} onChange={onChange} />
      <input
        className="ux-scope__search"
        type="search"
        value={query}
        placeholder="Filter verbs..."
        aria-label="Filter verbs"
        onChange={(e) => setQuery(e.target.value)}
      />
      <div className="ux-scope__tree">
        {nouns.map(([noun, list]) => (
          <ScopeBuilderNoun
            key={noun}
            noun={noun}
            list={list}
            value={value}
            openNouns={openNouns}
            setOpenNouns={setOpenNouns}
            q={q}
            disabled={disabled}
            add={add}
            onChange={onChange}
          />
        ))}
        {verbs.length === 0 && <span className="ux-picker__none">No verbs available to this caller.</span>}
      </div>
      <ScopeBuilderPreview matched={matched} matchedHigh={matchedHigh} deadPatterns={deadPatterns} warn={warn} />
    </div>
  );
}

export type { ScopeVerb } from "./scopeMatches";
