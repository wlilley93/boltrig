import type { ReactNode } from "react";

// Starter icon paths, traced from the design's icon set (stroke, 24 viewBox).
const STARTERS: Array<{ title: string; desc: string; icon: string[] }> = [
  {
    title: "Find something out",
    desc: "Read across your systems and come back with an answer",
    icon: [
      "M4.5 4.5h6a3 3 0 0 1 3 3v12a2.5 2.5 0 0 0-2.5-2.5h-6.5z",
      "M19.5 4.5h-6a3 3 0 0 0-3 3v12a2.5 2.5 0 0 1 2.5-2.5h6.5z",
    ],
  },
  {
    title: "Draft something",
    desc: "Written in your voice, and sent to nobody until you say",
    icon: ["M6 3.5h7l5 5v12H6z", "M13 3.5V9h5"],
  },
  {
    title: "Work through a list",
    desc: "The same job across many records, a helper on each",
    icon: ["M4 4.5h16v5H4zM4 14.5h16v5H4z", "M7.5 7h.01M7.5 17h.01"],
  },
  {
    title: "Keep an eye on something",
    desc: "A standing goal it keeps pursuing until you stop it",
    icon: ["M5 12.5l4.5 4.5L19 7"],
  },
];

// The decided target opens a new chat with a quiet mark, one question and four
// starters. It does NOT open with the Stage at hero size: that placement came
// from ADR 0025 and the new target supersedes it here, which also removes the
// unbounded square that pushed the composer off a short window. Clicking a
// starter fills the composer draft; it never sends.
export function Welcome({
  onStarter,
  children,
}: {
  onStarter?(text: string): void;
  children: ReactNode;
}) {
  return (
    <section className="welcome">
      <h1>What needs doing?</h1>
      {children}
      <div className="starters">
        {STARTERS.map(({ title, desc, icon }) => (
          <button
            className="starter-card"
            key={title}
            onClick={() => onStarter?.(title)}
            title={desc}
            type="button"
          >
            <span aria-hidden className="starter-icon">
              <svg fill="none" height="16" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" viewBox="0 0 24 24" width="16">
                {icon.map((d) => <path d={d} key={d} />)}
              </svg>
            </span>
            <span className="starter-title">{title}</span>
          </button>
        ))}
      </div>
    </section>
  );
}
