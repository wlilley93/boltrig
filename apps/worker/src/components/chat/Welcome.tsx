import type { ReactNode } from "react";

// New tasks start with one question and the real prompt controls. The older
// four suggested openers duplicated command discovery and added visual noise.
export function Welcome({ children }: { children: ReactNode }) {
  return (
    <section className="welcome">
      <h1>What needs doing?</h1>
      {children}
    </section>
  );
}
