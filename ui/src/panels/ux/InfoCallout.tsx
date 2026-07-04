import type { ReactNode } from "react";

// --- Segmented: a small set of mutually exclusive choices, always visible --
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
