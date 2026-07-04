import type { ReactNode } from "react";

import { Hint } from "../ux";

import type { ScopeVerb } from "./scopeMatches";

export interface ScopeBuilderPreviewProps {
  matched: ScopeVerb[];
  matchedHigh: number;
  deadPatterns: string[];
  warn?: ReactNode;
}

export function ScopeBuilderPreview({ matched, matchedHigh, deadPatterns, warn }: ScopeBuilderPreviewProps) {
  return (
    <>
      <Hint>A pattern like ticket.* also covers verbs added later.</Hint>
      <details className="ux-scope__preview">
        <summary>
          Matches {matched.length} {matched.length === 1 ? "verb" : "verbs"} today ({matchedHigh} high
          consequence)
        </summary>
        <div className="ux-scope__matchlist">
          {matched.length === 0 ? (
            <span className="ux-hint">Nothing matches yet.</span>
          ) : (
            matched.map((v) => (
              <code key={v.id} className="tag">
                {v.id}
              </code>
            ))
          )}
        </div>
      </details>
      {deadPatterns.length > 0 && (
        <p className="ux-scope__warn">
          {deadPatterns.join(", ")} {deadPatterns.length === 1 ? "matches" : "match"} no verbs today.
          Patterns apply to future verbs that fit.
        </p>
      )}
      {warn != null && <p className="ux-scope__warn">{warn}</p>}
    </>
  );
}
