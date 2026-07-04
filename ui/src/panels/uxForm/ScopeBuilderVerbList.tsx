import { CONSEQUENCE, StatusBadge } from "../ux";

import { grantMatches, type ScopeVerb } from "./scopeMatches";

export interface ScopeBuilderVerbListProps {
  shown: ScopeVerb[];
  value: string[];
  disabled: boolean;
  add: (p: string) => void;
}

export function ScopeBuilderVerbList({ shown, value, disabled, add }: ScopeBuilderVerbListProps) {
  return (
    <div className="ux-scope__verbs">
      {shown.map((v) => {
        const covered = value.some((p) => grantMatches(p, v.id));
        return (
          <div key={v.id} className="ux-scope__row">
            <span className="ux-scope__verbid">{v.id}</span>
            {v.consequence === "high" && <StatusBadge value="high" glossary={CONSEQUENCE} />}
            {covered ? (
              <span className="ux-scope__covered">covered</span>
            ) : (
              <button
                type="button"
                className="btn btn--sm btn--ghost"
                disabled={disabled}
                aria-label={`Add ${v.id}`}
                onClick={() => add(v.id)}
              >
                Add
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
