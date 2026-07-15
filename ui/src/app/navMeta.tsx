import type { ReactNode } from "react";

// One-line purpose per nav id (zone rows + ops columns), surfaced as title
// hints. Ids match the deck row / column keys from deckMap.
export const HINT: Record<string, string> = {
  chat: "Converse with the orchestrator",
  agents: "The durable agent org chart and worker pool",
  automations: "Workflows: pick one to see its canvas",
  settings: "Account, tokens, connections, directory",
  home: "Your dashboard: approvals, runs and work",
  router: "Nouns, verbs and adapter health",
  studio: "Authoring: skills, router, adapters, workflows",
  dev: "Invoke a verb, spawn an agent, view adapter source",
  kanban: "Work items by status",
  approvals: "Pending human-in-the-loop",
  insight: "Cost, audit and runs (scoped)",
  eval: "No-escalation evaluation harness",
  memory: "Recall, browse, remember and ingest (scoped)",
  admin: "Manifest config, history, credentials",
  me: "Personal agent, prefs and memory",
  runs: "Trace live and completed work",
  build: "Agents, workflows and capabilities",
  operate: "Queue, approvals and system posture",
  health: "Runtime and dependency readiness",
};

// Filled geometric icons for the sidebar rail (kept dependency-free: small inline
// SVGs, fill = currentColor, so they inherit the nav item's colour + glow).
export const ICON: Record<string, ReactNode> = {
  home: (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" opacity="0.85"><path d="M12 3L4 9.5V21h6v-6h4v6h6V9.5L12 3z" /></svg>
  ),
  runs: (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M5 5v14M5 8h5a3 3 0 0 1 3 3v2a3 3 0 0 0 3 3h3" /><circle cx="5" cy="5" r="2" fill="currentColor" stroke="none" /><circle cx="19" cy="16" r="2" fill="currentColor" stroke="none" /></svg>
  ),
  build: (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M4 7h16M7 4v6M17 4v6M5 13h6v6H5zM15 13h4v6h-4" /></svg>
  ),
  operate: (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M4 6h16M4 12h16M4 18h16" /><circle cx="8" cy="6" r="2" fill="currentColor" stroke="none" /><circle cx="15" cy="12" r="2" fill="currentColor" stroke="none" /><circle cx="11" cy="18" r="2" fill="currentColor" stroke="none" /></svg>
  ),
  health: (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12h4l2-5 4 10 2-5h6" /></svg>
  ),
  router: (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" opacity="0.85"><circle cx="6" cy="12" r="3" /><circle cx="18" cy="6" r="2.5" /><circle cx="18" cy="18" r="2.5" /><path d="M9 12h2.5M11.5 12V6.5H15.5M11.5 12v5.5H15.5" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg>
  ),
  studio: (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" opacity="0.85"><rect x="3" y="14" width="5" height="5" rx="1" /><rect x="16" y="4" width="5" height="5" rx="1" /><rect x="16" y="15" width="5" height="5" rx="1" /><path d="M8 16.5h3.5M11.5 16.5V7H16" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg>
  ),
  dev: (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" opacity="0.85"><rect x="4" y="5" width="16" height="14" rx="1.5" /><path d="M8 10l2.5 2L8 14M13.5 14H16" fill="none" stroke="#04060D" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
  ),
  chat: (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" opacity="0.85"><path d="M5 3h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9l-4 4V5a2 2 0 0 1 2-2z" /></svg>
  ),
  agents: (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" opacity="0.85"><circle cx="12" cy="5" r="3" /><circle cx="5" cy="18" r="2.5" /><circle cx="19" cy="18" r="2.5" /><path d="M12 8v4M8 16l4-4 4 4" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg>
  ),
  automations: (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" opacity="0.85"><circle cx="5" cy="12" r="2.5" /><circle cx="12" cy="12" r="2.5" /><circle cx="19" cy="12" r="2.5" /><rect x="7" y="11" width="3" height="2" rx="1" /><rect x="14" y="11" width="3" height="2" rx="1" /></svg>
  ),
  kanban: (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" opacity="0.85"><rect x="3" y="3" width="5" height="18" rx="1.5" /><rect x="10" y="3" width="5" height="13" rx="1.5" /><rect x="17" y="3" width="5" height="9" rx="1.5" /></svg>
  ),
  approvals: (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" opacity="0.85"><path d="M12 2L4 6v6c0 5.5 3.4 8.5 8 11 4.6-2.5 8-5.5 8-11V6l-8-4z" /><path d="M9 12l2 2 4-4" fill="none" stroke="#04060D" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
  ),
  insight: (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" opacity="0.85"><rect x="6" y="12" width="4" height="8" rx="1" /><rect x="12" y="7" width="4" height="13" rx="1" /><rect x="18" y="14" width="4" height="6" rx="1" /><path d="M2 20h22" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg>
  ),
  eval: (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" opacity="0.85"><rect x="5" y="3" width="14" height="18" rx="1.5" /><path d="M9 10l2 2 4-4" fill="none" stroke="#04060D" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
  ),
  memory: (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" opacity="0.85"><ellipse cx="12" cy="6" rx="8" ry="4" /><path d="M4 6v5c0 2.2 3.6 4 8 4s8-1.8 8-4V6" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M4 11v5c0 2.2 3.6 4 8 4s8-1.8 8-4v-5" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg>
  ),
  admin: (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" opacity="0.85"><circle cx="9" cy="8" r="2.5" /><circle cx="15" cy="16" r="2.5" /><path d="M4 8h4.5M13.5 16H20M9 10.5v7M15 6.5v7" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg>
  ),
  me: (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" opacity="0.85"><circle cx="12" cy="8" r="3.5" /><path d="M5 20c0-3.9 3.1-7 7-7s7 3.1 7 7" /></svg>
  ),
  settings: (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" opacity="0.85"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9c.26.6.77 1.02 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>
  ),
};
