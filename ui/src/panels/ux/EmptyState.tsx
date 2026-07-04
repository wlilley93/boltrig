import type { ReactNode } from "react";

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
