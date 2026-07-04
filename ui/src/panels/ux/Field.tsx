import type { ReactNode } from "react";

// --- Field: label + control + hint + example -------------------------------
export function Field({
  label,
  hint,
  example,
  htmlFor,
  required,
  wide,
  error,
  meta,
  children,
}: {
  label: ReactNode;
  hint?: ReactNode; // what it is + why it matters
  example?: ReactNode; // a concrete value
  htmlFor?: string;
  required?: boolean;
  wide?: boolean;
  // N8 (P11): field-scoped error, below the hint; flips child control borders.
  // Callers wire aria-invalid and aria-describedby={`${id}-error`} on the control.
  error?: ReactNode;
  // N8 (P11): right-aligned live derived fact in the label row (a match count,
  // a char budget); never a validation message.
  meta?: ReactNode;
  children: ReactNode;
}) {
  const labelNode = (
    <label className="ux-field__label" htmlFor={htmlFor}>
      {label}
      {required && <em className="ux-field__req" title="required"> *</em>}
    </label>
  );
  return (
    <div
      className={`ux-field ${wide ? "ux-field--wide" : ""} ${error != null ? "ux-field--error" : ""}`}
    >
      {meta != null ? (
        <span className="ux-field__labelrow">
          {labelNode}
          <span className="ux-field__meta">{meta}</span>
        </span>
      ) : (
        labelNode
      )}
      {children}
      {hint && <span className="ux-field__hint">{hint}</span>}
      {example != null && (
        <span className="ux-field__example">
          e.g. <code>{example}</code>
        </span>
      )}
      {error != null && (
        <span
          className="ux-field__error"
          role="alert"
          id={htmlFor ? `${htmlFor}-error` : undefined}
        >
          {error}
        </span>
      )}
    </div>
  );
}
