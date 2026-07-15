// Route <-> deck-cell mapping and the visible row model. The Deck renders a
// 2D grid of rows (zones) and columns (slides); this module is the single
// translation between the hash router's Route and a cell address
// { rowId, colKey }, plus the role-filtered DeckRow[] builder the App feeds
// the Deck each render.
//
// Beat 1: the agents / automations rows carry only their anchor column; the
// agentCols / automationCols parameters are the seam Beats 2-3 plug per-agent
// and per-step columns into without touching this mapping again.

import type { Route } from "../router";
import type { DeckCol, DeckRow } from "./Deck";

// Roles permitted to author (studios, agents, automations) / administer. The
// server is the real gate (403); these only decide what the deck offers up
// front. App re-exports AUTHOR_ROLES so existing imports from "../App" hold.
export const AUTHOR_ROLES: ReadonlySet<string> = new Set([
  "org-admin",
  "department-head",
  "manager",
  "lead",
  "integrator",
]);
export const ADMIN_ROLES: ReadonlySet<string> = new Set(["org-admin"]);

// The ops row: the remaining tabs as columns, each keeping its existing route
// (#/<tab>) so every legacy deep link and the command palette keep resolving.
// colKey = tab id; gate hides a column for unqualified roles (cosmetic only).
const OPS_COLS: ReadonlyArray<{
  key: string;
  label: string;
  gate?: (role: string) => boolean;
}> = [
  { key: "home", label: "Home" },
  { key: "runs", label: "Runs" },
  { key: "build", label: "Build" },
  { key: "operate", label: "Operate" },
  { key: "router", label: "Router" },
  { key: "studio", label: "Studio", gate: (r) => AUTHOR_ROLES.has(r) },
  { key: "dev", label: "Dev console", gate: (r) => AUTHOR_ROLES.has(r) },
  { key: "kanban", label: "Kanban" },
  { key: "approvals", label: "Approvals" },
  { key: "insight", label: "Insight" },
  { key: "eval", label: "Eval" },
  { key: "memory", label: "Memory" },
  { key: "health", label: "Health" },
  { key: "admin", label: "Admin", gate: (r) => ADMIN_ROLES.has(r) },
  { key: "channels", label: "Channels", gate: (r) => ADMIN_ROLES.has(r) },
  { key: "me", label: "Me" },
];

// The settings row: one column per section, keyed by section id (the spec's
// section 0 grid amendment). Routes: #/settings (anchor) and
// #/settings/<section>. Order and ids mirror the retired SETTINGS_TABS; the
// organisation column is gated to org-admins (cosmetic only, like the ops
// admin column - the server 403 stays authoritative). Exported so the
// settings anchor renders its card directory from the same list.
export const SETTINGS_COLS: ReadonlyArray<{
  key: string;
  label: string;
  gate?: (role: string) => boolean;
}> = [
  { key: "account", label: "Account & Profile" },
  { key: "appearance", label: "Appearance & Accessibility" },
  { key: "notifications", label: "Notifications" },
  { key: "developer", label: "Developer & Connections" },
  { key: "agent", label: "Personal Agent" },
  { key: "privacy", label: "Privacy & My Data" },
  { key: "security", label: "Security & Sessions" },
  {
    key: "organisation",
    label: "Organisation",
    gate: (r) => ADMIN_ROLES.has(r),
  },
];

function anchor(key: string, label: string): DeckCol {
  return { key, label, path: `/${key}` };
}

// The visible rows for the current role, in vertical order. Role gates are
// cosmetic (the server 403 stays authoritative); rows/cols are re-derived from
// the CURRENT role each render so the dev IdentityBar changes them live.
export function buildRows(
  role: string,
  agentCols: DeckCol[] = [],
  automationCols: DeckCol[] = [],
): DeckRow[] {
  const author = AUTHOR_ROLES.has(role);
  const rows: DeckRow[] = [
    { id: "chat", label: "Chat", cols: [anchor("chat", "Chat")] },
  ];
  if (author) {
    rows.push({
      id: "agents",
      label: "Agents",
      cols: [anchor("agents", "Agents"), ...agentCols],
    });
    rows.push({
      id: "automations",
      label: "Automations",
      cols: [anchor("automations", "Automations"), ...automationCols],
    });
  }
  rows.push({
    id: "settings",
    label: "Settings",
    cols: [
      anchor("settings", "Settings"),
      ...SETTINGS_COLS.filter((c) => !c.gate || c.gate(role)).map((c) => ({
        key: c.key,
        label: c.label,
        path: `/settings/${c.key}`,
      })),
    ],
  });
  rows.push({
    id: "ops",
    label: "Ops",
    cols: OPS_COLS.filter((c) => !c.gate || c.gate(role)).map((c) => ({
      key: c.key,
      label: c.label,
      path: `/${c.key}`,
    })),
  });
  return rows;
}

// TOTAL route -> cell mapping over the rows the caller passes:
//   - a row id matching the tab wins; segs[1] selects a column when it names
//     one, otherwise that row's anchor (so #/settings/<section> resolves to
//     its column, and a gated or unknown section - e.g. #/settings/organisation
//     while not org-admin - falls back to the settings anchor, the same
//     treatment the gated ops columns get)
//   - otherwise a column key matching the tab wins (the ops tabs keep their
//     legacy #/<tab> routes)
//   - unknown tabs and #/runs/<id> land on the chat anchor (the run drawer is
//     an orthogonal overlay driven by route.runId, never a deck move)
export function routeToCell(
  route: Route,
  rows: DeckRow[],
): { rowId: string; colKey: string } {
  const tab = route.tab;
  if (tab === "runs") {
    const ops = rows.find((row) => row.id === "ops");
    const runs = ops?.cols.find((col) => col.key === "runs");
    if (ops && runs) return { rowId: ops.id, colKey: runs.key };
  } else {
    const row = rows.find((r) => r.id === tab);
    if (row && row.cols.length > 0) {
      const sub =
        tab === "automations" && route.segs[2] === "step"
          ? route.segs[3]
          : route.segs[1];
      const col = sub ? row.cols.find((c) => c.key === sub) : undefined;
      return { rowId: row.id, colKey: (col ?? row.cols[0]).key };
    }
    for (const r of rows) {
      const col = r.cols.find((c) => c.key === tab);
      if (col) return { rowId: r.id, colKey: col.key };
    }
  }
  const chat = rows.find((r) => r.id === "chat");
  if (chat && chat.cols.length > 0) {
    return { rowId: chat.id, colKey: chat.cols[0].key };
  }
  // buildRows always includes the chat row; this last resort only keeps the
  // function total for arbitrary caller-supplied rows.
  const first = rows[0];
  return first && first.cols.length > 0
    ? { rowId: first.id, colKey: first.cols[0].key }
    : { rowId: "chat", colKey: "chat" };
}
