// The settings surface the decided target draws: ten sections under four heads,
// reachable from a nav that replaces the app sidebar while you are in settings.
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

export const SETTINGS_SECTIONS: SettingsEntry[] = [
  {
    id: "you",
    label: "You",
    head: "You",
    title: "You",
    lead: "Your profile, how you sign in, and the sessions that are open right now.",
  },
  {
    id: "autonomy",
    label: "Autonomy",
    title: "Autonomy",
    lead: "How much boltrig may do before it stops and asks. Nothing here grants a permission it does not already have.",
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
    lead: "The files it may read, where their bytes live, and what it may quote.",
  },
  {
    id: "overnight",
    label: "Overnight",
    title: "Overnight",
    lead: "What it consolidates while nothing is running, and what it had to prove before anything was kept.",
  },
  {
    id: "health",
    label: "Health",
    title: "Health",
    lead: "What is ready, what is degraded, and what this build does not do yet.",
  },
  {
    id: "organisation",
    label: "Organisation",
    head: "The organisation",
    title: "Organisation",
    lead: "Who is in this workspace, and what the workspace itself allows.",
  },
  {
    id: "advanced",
    label: "Advanced",
    title: "Advanced",
    lead: "The device this client runs on, and the controls that are only safe when you know why you want them.",
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
  return SETTINGS_SECTIONS.find((entry) => entry.id === id) ?? SETTINGS_SECTIONS[0];
}

export function isSettingsSection(value: string): value is SettingsSection {
  return SETTINGS_SECTIONS.some((entry) => entry.id === value);
}
