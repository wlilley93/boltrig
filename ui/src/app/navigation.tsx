import type { ReactNode } from "react";

import { ADMIN_ROLES, AUTHOR_ROLES } from "@/deck/deckMap";
import { ICON } from "@/app/navMeta";

export type ConsoleZone = "home" | "chat" | "runs" | "build" | "operate" | "settings";

export interface ConsoleNavItem {
  id: string;
  label: string;
  path: string;
  description: string;
  icon?: ReactNode;
  gate?: (role: string) => boolean;
}

export const PRIMARY_NAV: readonly ConsoleNavItem[] = [
  {
    id: "home",
    label: "Home",
    path: "/home",
    description: "Operational overview",
    icon: ICON.home,
  },
  {
    id: "chat",
    label: "Chat",
    path: "/chat",
    description: "Work with Boltrig",
    icon: ICON.chat,
  },
  {
    id: "runs",
    label: "Runs",
    path: "/runs",
    description: "Trace live and completed work",
    icon: ICON.runs,
  },
  {
    id: "build",
    label: "Build",
    path: "/build",
    description: "Agents, workflows and capabilities",
    icon: ICON.build,
  },
  {
    id: "operate",
    label: "Operate",
    path: "/operate",
    description: "Queue, approvals and system posture",
    icon: ICON.operate,
  },
];

export const BUILD_NAV: readonly ConsoleNavItem[] = [
  {
    id: "agents",
    label: "Agents",
    path: "/agents",
    description: "Agent profiles and fleet",
    gate: (role) => AUTHOR_ROLES.has(role),
  },
  {
    id: "automations",
    label: "Workflows",
    path: "/automations",
    description: "Design and run governed workflows",
    gate: (role) => AUTHOR_ROLES.has(role),
  },
  { id: "router", label: "Registry", path: "/router", description: "Nouns, verbs and bindings" },
  {
    id: "studio",
    label: "Integrations",
    path: "/studio",
    description: "Adapters, MCP servers and authoring",
    gate: (role) => AUTHOR_ROLES.has(role),
  },
  { id: "memory", label: "Memory", path: "/memory", description: "Recall, sources and retention" },
  { id: "eval", label: "Evaluations", path: "/eval", description: "Safety and quality evaluations" },
];

export const OPERATE_NAV: readonly ConsoleNavItem[] = [
  { id: "kanban", label: "Work queue", path: "/kanban", description: "Work by lifecycle state" },
  {
    id: "approvals",
    label: "Approvals",
    path: "/approvals",
    description: "Human decisions blocking work",
  },
  {
    id: "insight",
    label: "Audit & costs",
    path: "/insight",
    description: "Scoped audit, spend and budgets",
  },
  { id: "health", label: "Health", path: "/health", description: "Runtime and dependency readiness" },
  {
    id: "channels",
    label: "Channels",
    path: "/channels",
    description: "Connected communication surfaces",
    gate: (role) => ADMIN_ROLES.has(role),
  },
  {
    id: "admin",
    label: "Admin",
    path: "/admin",
    description: "Organisation and runtime configuration",
    gate: (role) => ADMIN_ROLES.has(role),
  },
];

const BUILD_TABS = new Set(["build", "agents", "automations", "router", "studio", "dev", "memory", "eval"]);
const OPERATE_TABS = new Set(["operate", "kanban", "approvals", "insight", "health", "channels", "admin"]);

export function visibleItems(items: readonly ConsoleNavItem[], role: string): ConsoleNavItem[] {
  return items.filter((item) => !item.gate || item.gate(role));
}

export function zoneForTab(tab: string): ConsoleZone {
  if (BUILD_TABS.has(tab)) return "build";
  if (OPERATE_TABS.has(tab)) return "operate";
  if (tab === "home" || tab === "runs" || tab === "settings") return tab;
  return "chat";
}

export function itemForTab(tab: string, role: string): ConsoleNavItem | undefined {
  return [...PRIMARY_NAV, ...visibleItems(BUILD_NAV, role), ...visibleItems(OPERATE_NAV, role)].find(
    (item) => item.id === tab,
  );
}
