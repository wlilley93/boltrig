import type { ReactNode } from "react";

export type IconName = "home" | "chat" | "goal" | "work" | "agent" | "flow" | "run" | "approval" | "search" | "panel" | "sun" | "moon" | "plus" | "spark" | "pause" | "play" | "check" | "warning";

const paths: Record<IconName, ReactNode> = {
  home: <><path d="m3 11 9-8 9 8"/><path d="M5 10v10h14V10"/><path d="M9 20v-6h6v6"/></>,
  chat: <><path d="M5 18.5 3 21v-5a8 8 0 1 1 3 3"/><path d="M8 10h8M8 14h5"/></>,
  goal: <><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="m14 10 7-7"/></>,
  work: <><rect x="3" y="6" width="18" height="14" rx="2"/><path d="M8 6V4h8v2M3 11h18"/></>,
  agent: <><circle cx="12" cy="8" r="3"/><path d="M5 20c0-4 3-7 7-7s7 3 7 7"/><path d="M19 5v4M17 7h4"/></>,
  flow: <><rect x="3" y="3" width="6" height="6" rx="1"/><rect x="15" y="15" width="6" height="6" rx="1"/><path d="M9 6h4a4 4 0 0 1 4 4v5"/></>,
  run: <><path d="m8 5 10 7-10 7z"/></>,
  approval: <><path d="M12 3 4 6v5c0 5 3 8 8 10 5-2 8-5 8-10V6z"/><path d="m8.5 12 2 2 5-5"/></>,
  search: <><circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/></>,
  panel: <><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/></>,
  sun: <><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M19 5l-1.5 1.5M6.5 17.5 5 19"/></>,
  moon: <path d="M20 15a8 8 0 0 1-11-11 8.5 8.5 0 1 0 11 11z"/>,
  plus: <path d="M12 5v14M5 12h14"/>,
  spark: <><path d="m12 3 1.4 4.2L18 9l-4.6 1.8L12 15l-1.4-4.2L6 9l4.6-1.8z"/><path d="m19 15 .7 2.3L22 18l-2.3.7L19 21l-.7-2.3L16 18l2.3-.7z"/></>,
  pause: <><path d="M8 5v14M16 5v14"/></>,
  play: <path d="m8 5 10 7-10 7z"/>,
  check: <path d="m5 12 4 4L19 6"/>,
  warning: <><path d="M12 3 2.5 20h19z"/><path d="M12 9v5M12 17h.01"/></>,
};

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return <svg aria-hidden="true" className="proto-icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}
