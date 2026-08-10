import { SHORTCUTS } from "../../shortcuts";
import { settingsEntry, type SettingsSection } from "../../settingsSections";

// A declarative index of every settings row, so one query can search all ten
// sections rather than only the nav labels. Rows for the console-idiom
// sections mirror what those panes actually draw; rows for the larger
// dedicated app surfaces remain searchable without making them the default
// settings experience.

export interface SettingsIndexRow {
  section: SettingsSection;
  title: string;
  desc?: string;
  tech?: string;
}

export const SETTINGS_INDEX: SettingsIndexRow[] = [
  // You — the compact identity and appearance surface.
  { section: "you", title: "Theme", desc: "System, light or dark", tech: "theme" },
  { section: "you", title: "Locale", tech: "locale" },
  { section: "you", title: "Timezone", tech: "timezone" },
  { section: "you", title: "Notification routes", desc: "Routes for events that need you" },
  { section: "you", title: "Personal agent", desc: "Your delegated agent" },
  { section: "you", title: "Personal access tokens", desc: "Developer access" },
  { section: "you", title: "Signed-in sessions", desc: "Revoke other devices" },
  { section: "you", title: "Two-factor authentication", desc: "Authenticator and recovery codes" },
  { section: "you", title: "Change password" },
  { section: "you", title: "Activity and export", desc: "Your recent account activity" },

  // Autonomy — the honest reading of what stops a run.
  { section: "autonomy", title: "Every consequential verb asks first", desc: "Approval is decided by the kernel against workspace policy", tech: "hitl" },
  { section: "autonomy", title: "Ceilings that actually stop work", desc: "A ceiling without a hard stop does not halt a run" },
  { section: "autonomy", title: "Credentials never reach this client" },

  // Spending.
  { section: "spend", title: "Total so far", desc: "Every governed call this workspace has paid for" },
  { section: "spend", title: "Ceilings", desc: "Spend meters per budget window" },
  { section: "spend", title: "Where it went", desc: "Spend attributed per actor" },

  // Keyboard shortcuts — drawn from the registry, one source of truth.
  ...SHORTCUTS.map((shortcut) => ({
    section: "shortcuts" as SettingsSection,
    title: shortcut.label,
    desc: shortcut.desc,
    tech: shortcut.keys.join(" "),
  })),

  // Knowledge — KnowledgeView's real surface.
  { section: "knowledge", title: "Knowledge providers", desc: "Where indexed passages live, and their health" },
  { section: "knowledge", title: "Upload knowledge", desc: "Governed assets with revisions and citations" },

  // Overnight.
  { section: "overnight", title: "What the record shows", desc: "Gate receipts from overnight practice" },
  { section: "overnight", title: "What a night has to prove", desc: "The mechanical checks before anything is kept" },
  { section: "overnight", title: "The rules it works under", desc: "Rebuild from base, habits never facts, erasure by exclusion" },

  // Health.
  { section: "health", title: "Everything that has to be working", desc: "Readiness checks, in plain words" },
  { section: "health", title: "What boltrig does not do yet", desc: "Limits you can see" },
  { section: "health", title: "Waiting on a person", desc: "Approvals and questions in the inbox" },
  { section: "health", title: "Spent today", desc: "Against the daily ceiling, when one is set" },

  // Organisation — OrganisationView's real surface.
  { section: "organisation", title: "Members and roles", desc: "Who is here and what they may do" },
  { section: "organisation", title: "Workspaces", desc: "Membership-scoped workspaces" },
  { section: "organisation", title: "Organisation policy", desc: "Name, slug, two-factor requirement, AI keys" },
  { section: "organisation", title: "Invitations", desc: "Pending invitations to this organisation" },

  // Advanced — the device view plus the kit's own switch.
  { section: "advanced", title: "Developer details", desc: "Shows the identifiers behind each row", tech: "developer_details" },
  { section: "advanced", title: "This device", desc: "Desktop shell or browser session" },
  { section: "advanced", title: "Device settings", desc: "Enrolled device controls" },
  { section: "advanced", title: "Desktop updates" },
  { section: "advanced", title: "Sign out", desc: "Revokes the current browser session cookie" },

  // Archived chats.
  { section: "archived", title: "Bring back a closed chat", desc: "Restores it to the sidebar; the record never left" },
];

export interface SettingsSearchGroup {
  section: SettingsSection;
  label: string;
  rows: SettingsIndexRow[];
}

/** Grouped matches, capped at 8 rows per section as the design does. */
export function searchSettings(query: string): SettingsSearchGroup[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [];
  const groups: SettingsSearchGroup[] = [];
  for (const row of SETTINGS_INDEX) {
    const entry = settingsEntry(row.section);
    const hay = `${row.title} ${row.desc ?? ""} ${row.tech ?? ""} ${entry.label}`.toLowerCase();
    if (!hay.includes(needle)) continue;
    let group = groups.find((candidate) => candidate.section === row.section);
    if (!group) {
      group = { section: row.section, label: entry.label, rows: [] };
      groups.push(group);
    }
    if (group.rows.length < 8) group.rows.push(row);
  }
  return groups;
}
