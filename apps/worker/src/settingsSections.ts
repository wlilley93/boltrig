// The settings surface the decided target draws. Related behaviour controls live
// behind one section with four small views instead of competing for rail space.
// Operations remains a valid deep-linked pane for the workspace home, but it
// is deliberately not a settings-navigation entry in the canonical console,
// whose nav replaces the app sidebar while Settings is open.
// The list lives here rather than inside a component because the sidebar and the
// pane both read it, and a surface whose nav and content disagree about what
// sections exist is the defect that split Account, Organisation and Device in
// the first place.

export type SettingsSection =
  | "you"
  | "behaviour"
  // Legacy deep links remain valid and open the matching Behaviour view.
  | "sensing"
  | "sight"
  | "autonomy"
  | "spend"
  | "models"
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
    lead: "How boltrig looks, speaks and reaches you.",
  },
  {
    id: "behaviour",
    label: "Behaviour",
    title: "Behaviour",
    lead: "What Boltrig may notice, remember, and do while you are away.",
  },
  {
    id: "autonomy",
    label: "Autonomy",
    title: "Autonomy",
    lead: "Approval rules and spending limits that can stop work.",
  },
  {
    id: "spend",
    label: "Spending",
    title: "Spending",
    lead: "What work is allowed to cost, and what it has cost.",
  },
  {
    id: "models",
    label: "Models",
    title: "Models",
    lead: "Choose the models Boltrig uses.",
  },
  {
    id: "shortcuts",
    label: "Keyboard shortcuts",
    title: "Keyboard shortcuts",
    lead: "Everything you can reach without the mouse.",
  },
  {
    id: "health",
    head: "Its work",
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
    lead: "Device, session and developer settings.",
  },
  {
    id: "archived",
    label: "Archived chats",
    head: "Archive",
    title: "Archived chats",
    lead: "Out of the way, not gone. Everything they did is still in the record.",
  },
];

const LEGACY_BEHAVIOUR_ENTRIES: Partial<Record<SettingsSection, SettingsEntry>> = {
  sensing: {
    id: "sensing",
    label: "Behaviour",
    title: "Behaviour",
    lead: "What Boltrig may notice, remember, and do while you are away.",
  },
  sight: {
    id: "sight",
    label: "Behaviour",
    title: "Behaviour",
    lead: "What Boltrig may notice, remember, and do while you are away.",
  },
  knowledge: {
    id: "knowledge",
    label: "Behaviour",
    title: "Behaviour",
    lead: "What Boltrig may notice, remember, and do while you are away.",
  },
  overnight: {
    id: "overnight",
    label: "Behaviour",
    title: "Behaviour",
    lead: "What Boltrig may notice, remember, and do while you are away.",
  },
};

export function settingsEntry(id: string): SettingsEntry {
  if (Object.prototype.hasOwnProperty.call(LEGACY_BEHAVIOUR_ENTRIES, id)) {
    return LEGACY_BEHAVIOUR_ENTRIES[id as SettingsSection]!;
  }
  return SETTINGS_SECTIONS.find((entry) => entry.id === id) ?? SETTINGS_SECTIONS[0];
}

export function isSettingsSection(value: string): value is SettingsSection {
  // "operations" was a deep-linkable pane onto the kernel operations console -
  // runtime health, audit history, budget ceilings. None of it exists behind a
  // Hermes cell, so the section is gone rather than answering a deep link with
  // an empty page.
  return Object.prototype.hasOwnProperty.call(LEGACY_BEHAVIOUR_ENTRIES, value)
    || SETTINGS_SECTIONS.some((entry) => entry.id === value);
}

export function isBehaviourSettingsSection(section: SettingsSection): boolean {
  return section === "behaviour"
    || section === "sensing"
    || section === "sight"
    || section === "knowledge"
    || section === "overnight";
}

export function isActiveSettingsEntry(
  current: SettingsSection | undefined,
  entry: SettingsSection,
): boolean {
  if (!current) return false;
  return entry === "behaviour" ? isBehaviourSettingsSection(current) : current === entry;
}
