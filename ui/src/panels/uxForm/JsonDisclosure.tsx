import type { ReactNode } from "react";

// --- N9 JsonDisclosure: the collapsed JSON escape hatch (P10). ---------------
// Never the primary control (L1). The CALLER owns the two-way sync and the
// validity (amendment 9: an unparseable escape hatch blocks Save and slide
// navigation on every surface); pass the parse failure via error so the
// collapsed summary stays honest. summaryNote carries quiet facts like
// preserved unknown keys.
export function JsonDisclosure({
  value,
  onChange,
  error,
  summaryNote,
  label = "Advanced: edit as JSON",
  rows = 8,
  defaultOpen = false,
  disabled = false,
}: {
  value: string;
  onChange: (text: string) => void;
  error?: ReactNode;
  summaryNote?: ReactNode;
  label?: string;
  rows?: number;
  defaultOpen?: boolean;
  disabled?: boolean;
}) {
  return (
    <details className={`ux-jsond ${error ? "ux-jsond--invalid" : ""}`} open={defaultOpen}>
      <summary className="ux-jsond__summary">
        <span>{label}</span>
        {error ? (
          <span className="ux-jsond__flag" role="status">
            invalid JSON
          </span>
        ) : (
          summaryNote != null && <span className="ux-jsond__note">{summaryNote}</span>
        )}
      </summary>
      <div className="ux-jsond__body">
        <textarea
          className="ux-jsond__text"
          rows={rows}
          spellCheck={false}
          value={value}
          disabled={disabled}
          aria-invalid={error ? true : undefined}
          aria-label={label}
          onChange={(e) => onChange(e.target.value)}
        />
        {error != null && (
          <span className="ux-jsond__err" role="alert">
            {error}
          </span>
        )}
      </div>
    </details>
  );
}
