export interface ScopeBuilderChipsProps {
  value: string[];
  deadPatterns: string[];
  disabled: boolean;
  onChange: (v: string[]) => void;
}

export function ScopeBuilderChips({ value, deadPatterns, disabled, onChange }: ScopeBuilderChipsProps) {
  return (
    <div className="ux-chips__row">
      {value.length === 0 && (
        <span className="ux-hint">No grants yet. Add verbs or patterns from the list below.</span>
      )}
      {value.map((p) => {
        const dead = deadPatterns.includes(p);
        return (
          <span
            key={p}
            className={`ux-chips__chip ux-chips__chip--mono ${dead ? "ux-chips__chip--warn" : ""}`}
            title={dead ? "Matches no verbs today. It will apply to future verbs that fit." : undefined}
          >
            {p}
            <button
              type="button"
              className="ux-chips__rm"
              aria-label={`Remove ${p}`}
              disabled={disabled}
              onClick={() => onChange(value.filter((x) => x !== p))}
            >
              ×
            </button>
          </span>
        );
      })}
    </div>
  );
}
