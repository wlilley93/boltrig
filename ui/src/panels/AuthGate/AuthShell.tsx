import type { ReactNode } from "react";

function BoltMark() {
  return (
    <svg
      className="auth-card__mark"
      viewBox="0 0 24 24"
      width="34"
      height="34"
      fill="none"
      aria-hidden="true"
    >
      <path d="M7.5 3.5H4.5V20.5H7.5" stroke="currentColor" strokeWidth="2" strokeLinecap="square" />
      <path d="M16.5 3.5H19.5V20.5H16.5" stroke="currentColor" strokeWidth="2" strokeLinecap="square" />
      <path d="M13.2 4.5L8.5 12.6H12L10.8 19.5L15.5 11.4H12L13.2 4.5Z" fill="currentColor" />
    </svg>
  );
}

export function AuthShell({ title, lead, children }: { title: string; lead: string; children: ReactNode }) {
  return (
    <div className="auth-gate">
      <div className="auth-card">
        <div className="auth-card__brand">
          <BoltMark />
          <strong className="auth-card__word">boltrig</strong>
        </div>
        <h1 className="auth-card__title">{title}</h1>
        <p className="auth-card__lead">{lead}</p>
        {children}
      </div>
    </div>
  );
}
