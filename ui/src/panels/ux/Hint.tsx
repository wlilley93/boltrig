import type { ReactNode } from "react";

// --- Hint: a small calm line of guidance under a control or section --------
export function Hint({ children }: { children: ReactNode }) {
  return <p className="ux-hint">{children}</p>;
}
