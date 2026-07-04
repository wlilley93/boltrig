/** Disclosure (N11, P18): summary + body, count discoverable collapsed. */

import { useState, type MouseEvent, type ReactNode } from "react";

export function Disclosure({
  summary,
  changedCount,
  count,
  defaultOpen,
  open,
  onToggle,
  children,
}: {
  summary: ReactNode;
  // P18: non-default values must be discoverable without expanding
  changedCount?: number;
  count?: ReactNode; // free-form meta slot, e.g. "412 chars"
  defaultOpen?: boolean;
  open?: boolean; // controlled when set
  onToggle?: (open: boolean) => void;
  children: ReactNode;
}) {
  const [internalOpen, setInternalOpen] = useState(defaultOpen ?? false);
  const isOpen = open !== undefined ? open : internalOpen;
  const toggle = (e: MouseEvent<HTMLElement>) => {
    // this component owns the open state; the native toggle would fork it
    e.preventDefault();
    const next = !isOpen;
    if (open === undefined) setInternalOpen(next);
    onToggle?.(next);
  };
  return (
    <details className="ux-disclosure" open={isOpen}>
      <summary className="ux-disclosure__summary" onClick={toggle}>
        {summary}
        {changedCount !== undefined && changedCount > 0 && (
          <span className="ux-disclosure__count">{changedCount} changed</span>
        )}
        {count != null && <span className="ux-disclosure__count">{count}</span>}
      </summary>
      <div className="ux-disclosure__body">{children}</div>
    </details>
  );
}
