import type { ReactNode } from "react";

// --- Page intro: a plain-language purpose at the top of every panel --------
export function PageIntro({
  title,
  lead,
  how,
  howToggle,
  actions,
  children,
}: {
  title: ReactNode;
  lead?: ReactNode; // one sentence: what this page is for
  how?: ReactNode; // optional: how it works, in a calm aside
  // when set, the how paragraph is tucked behind a small "How this works"
  // info affordance instead of stacked under the lead (keeps busy panels calm)
  howToggle?: boolean;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="page-intro">
      <div className="page-intro__text">
        <h2>{title}</h2>
        {lead && <p className="page-intro__lead">{lead}</p>}
        {how &&
          (howToggle ? (
            <details className="page-intro__more">
              <summary className="page-intro__moretoggle">How this works</summary>
              <p className="page-intro__how">{how}</p>
            </details>
          ) : (
            <p className="page-intro__how">{how}</p>
          ))}
        {children}
      </div>
      {actions && <div className="page-intro__actions">{actions}</div>}
    </header>
  );
}
