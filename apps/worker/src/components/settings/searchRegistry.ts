import { SHORTCUTS } from "../../shortcuts";
import { settingsEntry, type SettingsSection } from "../../settingsSections";

// A declarative index of every settings row, so one query can search every
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
  { section: "you", title: "Companion", desc: "Familiar or Jarvis on the Stage", tech: "agent.character" },
  { section: "you", title: "Density", desc: "Comfortable or compact", tech: "density" },
  { section: "you", title: "Text size", desc: "Small, normal or large", tech: "font_scale" },
  { section: "you", title: "Reduced motion", desc: "Removes transitions and animation", tech: "a11y.reduced_motion" },
  { section: "you", title: "High contrast", desc: "Stronger borders and text", tech: "a11y.high_contrast" },
  { section: "you", title: "When something needs approving", desc: "Verified notification routes" },
  { section: "you", title: "Send those to", desc: "Verified delivery targets" },
  { section: "you", title: "Quiet hours", desc: "Not available" },
  { section: "you", title: "Take calls", desc: "Realtime voice availability is checked when a call starts" },
  { section: "you", title: "Hold the line at a gate", desc: "A call waits for approval in the originating chat" },
  { section: "you", title: "Locale", tech: "locale" },
  { section: "you", title: "Timezone", tech: "timezone" },
  { section: "you", title: "Notification routes", desc: "Routes for events that need you" },
  { section: "you", title: "Personal agent", desc: "Your delegated agent" },
  { section: "you", title: "Personal access tokens", desc: "Developer access" },
  { section: "you", title: "Signed-in sessions", desc: "Revoke other devices" },
  { section: "you", title: "Two-factor authentication", desc: "Authenticator and recovery codes" },
  { section: "you", title: "Change password" },
  { section: "you", title: "Activity and export", desc: "Your recent account activity" },

  // Camera and presence — the consent surface for this computer's hardware.
  { section: "sensing", title: "Camera", desc: "Whether this computer may watch the room at all", tech: "sensing.camera.enabled" },
  { section: "sensing", title: "Which camera", desc: "The camera this computer's agent published", tech: "sensing.camera.binding" },
  { section: "sensing", title: "Keep what it saw", desc: "How long frames and their observations survive", tech: "sensing.camera.retention_hours" },
  { section: "sensing", title: "Quiet hours", desc: "When nothing is captured, whatever a character asks for", tech: "sensing.camera.quiet_hours" },
  { section: "sensing", title: "Presence", desc: "Whether it is you in front of the camera", tech: "sensing.presence.enabled" },
  { section: "sensing", title: "The enrolled face", desc: "Kernel data about you; forget it here", tech: "sensing.enrollment" },
  { section: "sensing", title: "It is never included in a character bundle", desc: "Anchor images are the character's face; the enrolled face is yours" },
  { section: "sensing", title: "What a character is told", desc: "The honest refusal a character gets when a capability is off" },

  // Autonomy.
  { section: "autonomy", title: "Agent tool approvals", desc: "Ask for approval, approve safe actions, or grant full access for this runtime", tech: "agentic.approval_posture" },
  { section: "autonomy", title: "Hard-stop ceilings", desc: "A ceiling without a hard stop does not halt a run" },
  { section: "autonomy", title: "Credentials stay server-side" },

  // Spending.
  { section: "spend", title: "Total so far", desc: "Every governed call this workspace has paid for" },
  { section: "spend", title: "Ceilings", desc: "Spend meters per budget window" },
  { section: "spend", title: "Where it went", desc: "Spend attributed per actor" },

  // Models — exact Bifrost-facing names and their recoverable lifecycle.
  { section: "models", title: "Managed model routes", desc: "Exact model names shown in the chat switcher" },
  { section: "models", title: "Add a model", desc: "Add a governed Bifrost model choice" },
  { section: "models", title: "Change a model", desc: "Update an existing governed model choice" },
  { section: "models", title: "Remove a model", desc: "Retire a route everywhere while retaining its configuration" },
  { section: "models", title: "Restore a model", desc: "Return a retired route to model routing; switcher eligibility is checked separately" },

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
  { section: "health", title: "Current limits", desc: "Features and options not currently available" },
  { section: "health", title: "Waiting on a person", desc: "Approvals and questions in chat" },
  { section: "health", title: "Spent today", desc: "Against the daily ceiling, when one is set" },

  // Organisation — OrganisationView's real surface.
  { section: "organisation", title: "Members and roles", desc: "Who is here and what they may do" },
  { section: "organisation", title: "Workspaces", desc: "Membership-scoped workspaces" },
  { section: "organisation", title: "Organisation policy", desc: "Name, slug, two-factor requirement, AI keys" },
  { section: "organisation", title: "Invitations", desc: "Pending invitations to this organisation" },

  // Advanced — the device view plus the kit's own switch.
  { section: "advanced", title: "Developer details", desc: "Shows the identifiers behind each row", tech: "developer_details" },
  { section: "advanced", title: "This device", desc: "Desktop app or web browser" },
  { section: "advanced", title: "Boltrig Desktop", desc: "Download or connect this computer" },
  { section: "advanced", title: "Trusted computers", desc: "Revocable per-computer access" },
  { section: "advanced", title: "Desktop updates" },
  { section: "advanced", title: "Sign out", desc: "Signs out this account session" },

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
