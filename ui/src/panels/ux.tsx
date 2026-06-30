/* Shared "dreamy UX" primitives.
 *
 * The vocabulary every panel uses to explain itself and guide input: a page
 * intro that states the page's purpose in plain language, fields that carry a
 * label + a hint + an example, structured controls (select / segmented) in
 * place of naked free-text, and calm empty / denied / error states. Components
 * reference the design-system semantic tokens only (see styles.css). */

import type { ReactNode } from "react";

// --- Page intro: a plain-language purpose at the top of every panel --------
export function PageIntro({
  title,
  lead,
  how,
  actions,
  children,
}: {
  title: ReactNode;
  lead?: ReactNode; // one sentence: what this page is for
  how?: ReactNode; // optional: how it works, in a calm aside
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="page-intro">
      <div className="page-intro__text">
        <h2>{title}</h2>
        {lead && <p className="page-intro__lead">{lead}</p>}
        {how && <p className="page-intro__how">{how}</p>}
        {children}
      </div>
      {actions && <div className="page-intro__actions">{actions}</div>}
    </header>
  );
}

// --- Field: label + control + hint + example -------------------------------
export function Field({
  label,
  hint,
  example,
  htmlFor,
  required,
  wide,
  children,
}: {
  label: ReactNode;
  hint?: ReactNode; // what it is + why it matters
  example?: ReactNode; // a concrete value
  htmlFor?: string;
  required?: boolean;
  wide?: boolean;
  children: ReactNode;
}) {
  return (
    <div className={`ux-field ${wide ? "ux-field--wide" : ""}`}>
      <label className="ux-field__label" htmlFor={htmlFor}>
        {label}
        {required && <em className="ux-field__req" title="required"> *</em>}
      </label>
      {children}
      {hint && <span className="ux-field__hint">{hint}</span>}
      {example != null && (
        <span className="ux-field__example">
          e.g. <code>{example}</code>
        </span>
      )}
    </div>
  );
}

export interface Option {
  value: string;
  label: string;
  hint?: string;
}

// --- Select: a labelled dropdown over a known value space ------------------
export function Select({
  value,
  onChange,
  options,
  id,
  ariaLabel,
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  options: Option[];
  id?: string;
  ariaLabel?: string;
  disabled?: boolean;
}) {
  return (
    <select
      id={id}
      aria-label={ariaLabel}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

// --- Segmented: a small set of mutually exclusive choices, always visible --
export function Segmented({
  value,
  onChange,
  options,
  ariaLabel,
}: {
  value: string;
  onChange: (v: string) => void;
  options: Option[];
  ariaLabel?: string;
}) {
  return (
    <div className="seg" role="group" aria-label={ariaLabel}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          className={`btn btn--seg ${value === o.value ? "btn--seg-on" : ""}`}
          aria-pressed={value === o.value}
          title={o.hint}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

// --- Info callout: an explanatory aside (info / warn / consequence) --------
export function InfoCallout({
  tone = "info",
  title,
  children,
}: {
  tone?: "info" | "warn" | "consequence";
  title?: ReactNode;
  children: ReactNode;
}) {
  return (
    <aside className={`ux-callout ux-callout--${tone}`}>
      {title && <strong className="ux-callout__title">{title}</strong>}
      <div className="ux-callout__body">{children}</div>
    </aside>
  );
}

// --- Empty state: what's here + what to do next + a primary action ---------
export function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon?: ReactNode;
  title: ReactNode;
  body?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="ux-empty">
      {icon && <div className="ux-empty__icon" aria-hidden="true">{icon}</div>}
      <div className="ux-empty__title">{title}</div>
      {body && <p className="ux-empty__body">{body}</p>}
      {action && <div className="ux-empty__action">{action}</div>}
    </div>
  );
}

// --- Error / denied: show the server's reason faithfully, offer a retry ----
export function ErrorState({
  reason,
  onRetry,
}: {
  reason: ReactNode;
  onRetry?: () => void;
}) {
  return (
    <div className="ux-error" role="alert">
      <span className="ux-error__msg">{reason}</span>
      {onRetry && (
        <button type="button" className="btn btn--sm" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

// A failure from useFetch, rendered by KIND: a 403 reads as a calm "you don't
// have access" notice, a network failure as "can't reach the server" with a
// retry, and only a real server bug as a red alert. Returns null when there is
// no error, so a panel can drop it straight in.
export function FetchError({
  error,
  status,
  onRetry,
}: {
  error: string | null;
  status?: number | null;
  onRetry?: () => void;
}) {
  if (!error) return null;
  if (status === 403) {
    return <InfoCallout tone="warn">{error} Ask an admin to widen your access.</InfoCallout>;
  }
  if (status === 0) {
    return (
      <div className="ux-error" role="alert">
        <span className="ux-error__msg">{error}</span>
        {onRetry && (
          <button type="button" className="btn btn--sm" onClick={onRetry}>
            Try again
          </button>
        )}
      </div>
    );
  }
  return (
    <div className="ux-error" role="alert">
      <span className="ux-error__msg">{error}</span>
      {onRetry && (
        <button type="button" className="btn btn--sm" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

// --- Hint: a small calm line of guidance under a control or section --------
export function Hint({ children }: { children: ReactNode }) {
  return <p className="ux-hint">{children}</p>;
}

// --- Glossary: one home for the plain-language meaning of every status /
// run-state / governance term surfaced across the panels. Keep copy calm and
// glanceable; the badges below read their label + tooltip from here. ---------

interface Term {
  label: string;
  tip: string;
  cls: string; // a .badge--* modifier for colour
}

export const WORK_STATUS: Record<string, Term> = {
  pending: { label: "Pending", tip: "Queued. Not started yet.", cls: "badge--run-pending" },
  in_flight: { label: "In flight", tip: "Running right now.", cls: "badge--run-running" },
  blocked: { label: "Blocked", tip: "Stuck waiting on a dependency or a system.", cls: "badge--degraded" },
  awaiting_human: {
    label: "Awaiting human",
    tip: "Paused - needs a person to approve or answer. See Approvals.",
    cls: "badge--conseq-high",
  },
  done: { label: "Done", tip: "Finished successfully.", cls: "badge--ok" },
  failed: { label: "Failed", tip: "Stopped with an error.", cls: "badge--down" },
};

export const AUDIT_STATUS: Record<string, Term> = {
  ok: { label: "OK", tip: "Succeeded.", cls: "badge--ok" },
  denied: { label: "Denied", tip: "Blocked by a permission or policy.", cls: "badge--down" },
  degraded: { label: "Degraded", tip: "Worked, but a system was unhealthy.", cls: "badge--degraded" },
  error: { label: "Error", tip: "Failed.", cls: "badge--down" },
  pending_human: { label: "Paused", tip: "Paused for an approval.", cls: "badge--run-paused" },
};

export const HITL_TYPE: Record<string, Term> = {
  approval: { label: "Approval", tip: "Needs your sign-off before it runs.", cls: "badge--type-approval" },
  clarification: { label: "Question", tip: "The system has a question for you.", cls: "badge--type-clarification" },
  escalation: { label: "Escalated", tip: "Raised to you because it is above someone else's authority.", cls: "badge--type-escalation" },
};

export const HITL_URGENCY: Record<string, Term> = {
  blocking: { label: "Blocks the run", tip: "The run is paused until you answer.", cls: "badge--conseq-high" },
  async: { label: "Can wait", tip: "Answer when you get to it; the run is not blocked.", cls: "badge" },
};

export const CONSEQUENCE: Record<string, Term> = {
  high: { label: "High consequence", tip: "High-impact or hard to undo - requires human approval.", cls: "badge--conseq-high" },
  low: { label: "Low consequence", tip: "Routine - runs without sign-off.", cls: "badge--conseq-low" },
};

// A badge that renders a known term's friendly label + colour + a tooltip
// carrying the plain-language meaning. Unknown values fall back to the raw token.
export function StatusBadge({
  value,
  glossary,
  fallbackLabel,
}: {
  value: string | undefined | null;
  glossary: Record<string, Term>;
  fallbackLabel?: string;
}) {
  const key = (value ?? "").toString();
  const term = glossary[key];
  if (!term) {
    return <span className="badge" title={key}>{fallbackLabel ?? key ?? "-"}</span>;
  }
  return (
    <span className={`badge ${term.cls}`} title={term.tip}>
      {term.label}
    </span>
  );
}

// A plain label that carries a tooltip gloss (for column headers, dt labels,
// metric captions - anywhere a term needs a quiet explanation on hover).
export function TermTip({ term, children }: { term: string; children: ReactNode }) {
  return (
    <span className="ux-termtip" title={term}>
      {children}
    </span>
  );
}

// Notification value spaces (one source of truth for Me + Settings).
export const NOTIFY_EVENT_OPTIONS: Option[] = [
  { value: "approval", label: "Approval needed" },
  { value: "escalation", label: "Escalation" },
  { value: "work_status", label: "Work status change" },
  { value: "budget_alert", label: "Budget alert" },
  { value: "error", label: "Error" },
];
export const NOTIFY_CHANNEL_OPTIONS: Option[] = [
  { value: "in_app", label: "In-app" },
  { value: "email", label: "Email" },
  { value: "slack", label: "Slack" },
  { value: "teams", label: "Teams" },
  { value: "webhook", label: "Webhook" },
  { value: "pager", label: "Pager" },
];

// The canonical role value space (one source of truth; identity + admin + invite
// selects all read this so they can never drift). org-admin is the most
// powerful; agent the most limited.
export const ROLE_OPTIONS: Option[] = [
  { value: "org-admin", label: "org-admin", hint: "Full access to everything." },
  { value: "department-head", label: "department-head", hint: "Runs a department." },
  { value: "manager", label: "manager", hint: "Manages a team." },
  { value: "lead", label: "lead", hint: "Leads work within a team." },
  { value: "integrator", label: "integrator", hint: "Builds capability (skills, adapters, workflows)." },
  { value: "agent", label: "agent", hint: "The most limited role." },
];

// The bare role ids (one source of truth shared by the identity, admin and
// invite selects so they can never drift).
export const ROLE_VALUES: ReadonlyArray<string> = ROLE_OPTIONS.map((o) => o.value);
