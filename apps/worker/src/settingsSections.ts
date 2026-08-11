// The settings surface the decided target draws: ten sections under four heads.
// Operations remains a valid deep-linked pane for the workspace home, but it
// is deliberately not a settings-navigation entry in the canonical console,
// whose nav replaces the app sidebar while Settings is open.
// The list lives here rather than inside a component because the sidebar and the
// pane both read it, and a surface whose nav and content disagree about what
// sections exist is the defect that split Account, Organisation and Device in
// the first place.

export type SettingsSection =
  | "you"
  | "autonomy"
  | "spend"
  | "shortcuts"
  | "knowledge"
  | "overnight"
  | "health"
  | "operations"
  | "organisation"
  | "advanced"
  | "archived";

export interface SettingsEntry {
  id: SettingsSection;
  label: string;
  /** The head this section opens, when it opens one. */
  head?: string;
  title: string;
  lead: string;
}

const OPERATIONS_ENTRY: SettingsEntry = {
  id: "operations",
  label: "Operations",
  title: "Operations",
  lead: "Runtime posture, audit evidence and budget controls from the kernel.",
};

export const SETTINGS_SECTIONS: SettingsEntry[] = [
  {
    id: "you",
    label: "You",
    head: "You",
    title: "You",
    lead: "How boltrig looks, speaks and reaches you.",
  },
  {
    id: "autonomy",
    label: "Autonomy",
    title: "Autonomy",
    lead: "One decision governs the rest: how far boltrig may go before it asks.",
  },
  {
    id: "spend",
    label: "Spending",
    title: "Spending",
    lead: "What work is allowed to cost, and what it has cost.",
  },
  {
    id: "shortcuts",
    label: "Keyboard shortcuts",
    title: "Keyboard shortcuts",
    lead: "Everything you can reach without the mouse.",
  },
  {
    id: "knowledge",
    label: "Knowledge",
    head: "Its work",
    title: "Knowledge",
    lead: "What it can read, and what it is allowed to remember.",
  },
  {
    id: "overnight",
    label: "Overnight",
    title: "Overnight",
    lead: "Once a day it practises on your work, and keeps only what holds up.",
  },
  {
    id: "health",
    label: "Health",
    title: "Health",
    // The design's lead, kept because the pane now actually draws both halves:
    // the readiness readings and the boundaries card.
    lead: "What is working, and what boltrig cannot do yet.",
  },
  {
    id: "organisation",
    label: "Organisation",
    head: "The organisation",
    title: "Organisation",
    lead: "People, keys and the record. Admin-only.",
  },
  {
    id: "advanced",
    label: "Advanced",
    title: "Advanced",
    lead: "The workings. Safe to ignore, honest when you look.",
  },
  {
    id: "archived",
    label: "Archived chats",
    head: "Archive",
    title: "Archived chats",
    lead: "Out of the way, not gone. Everything they did is still in the record.",
  },
];

export function settingsEntry(id: string): SettingsEntry {
  if (id === "operations") return OPERATIONS_ENTRY;
  return SETTINGS_SECTIONS.find((entry) => entry.id === id) ?? SETTINGS_SECTIONS[0];
}

export function isSettingsSection(value: string): value is SettingsSection {
  return value === "operations" || SETTINGS_SECTIONS.some((entry) => entry.id === value);
}
