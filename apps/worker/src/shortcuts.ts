// The one shortcut registry. The Settings screen lists exactly what is here,
// and the keydown wiring is meant to read the same table, so the list and the
// behaviour cannot disagree — the old hand-written SHORTCUTS constant listed
// a ⌘B sidebar toggle that no handler anywhere bound, which is precisely the
// defect a single registry exists to prevent.
//
// Catalogue rule: a row is only added once its handler exists in this build.
// An unassigned key is not shown as though it worked.

export type ShortcutId =
  | "command-palette"
  | "new-chat"
  | "send"
  | "newline"
  | "close-overlay";

export interface ShortcutDef {
  id: ShortcutId;
  /** Display chips, mac-style symbols; each entry is one key badge. */
  keys: string[];
  label: string;
  desc: string;
  group: string;
  /** Where the handler lives, for the record (and for reviewers). */
  boundIn: string;
  /**
   * Present only for app-wide bindings. Contextual rows (send, newline,
   * escape) are bound by the surface that owns them and carry no global
   * matcher, so nothing here can fire them out of context.
   */
  matches?(event: KeyboardEvent): boolean;
}

function command(event: KeyboardEvent, key: string): boolean {
  return (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === key;
}

export const SHORTCUTS: ShortcutDef[] = [
  {
    id: "command-palette",
    keys: ["⌘K"],
    label: "Search everything",
    desc: "Chats, sections and settings, from one palette",
    group: "Getting around",
    boundIn: "components/shell/useAppNavigation.ts",
    matches: (event) => command(event, "k"),
  },
  {
    id: "new-chat",
    keys: ["⌘N"],
    label: "New chat",
    desc: "Start something new. Browsers may keep this for a new window",
    group: "Getting around",
    boundIn: "components/shell/useAppNavigation.ts",
    matches: (event) => command(event, "n"),
  },
  {
    id: "send",
    keys: ["↵"],
    label: "Send",
    desc: "Send what you have written",
    group: "In a conversation",
    boundIn: "components/chat/Composer.tsx",
  },
  {
    id: "newline",
    keys: ["⇧↵"],
    label: "New line",
    desc: "Without sending",
    group: "In a conversation",
    boundIn: "components/chat/Composer.tsx",
  },
  {
    id: "close-overlay",
    keys: ["Esc"],
    label: "Close what is open",
    desc: "The palette, a panel or a menu",
    group: "When something is open",
    boundIn: "CommandPalette.tsx, chat/TaskInspector.tsx, shell/useCompactNavigation.ts",
  },
];

export interface ShortcutGroup {
  title: string;
  rows: ShortcutDef[];
}

/** The registry grouped in declaration order, for the Settings screen. */
export const SHORTCUT_GROUPS: ShortcutGroup[] = SHORTCUTS.reduce<ShortcutGroup[]>(
  (groups, shortcut) => {
    const group = groups.find((candidate) => candidate.title === shortcut.group);
    if (group) group.rows.push(shortcut);
    else groups.push({ title: shortcut.group, rows: [shortcut] });
    return groups;
  },
  [],
);

/**
 * The lookup for app-level keydown wiring: returns the registry row an event
 * matches, or null. Contextual rows never match here by construction.
 */
export function globalShortcutFor(event: KeyboardEvent): ShortcutDef | null {
  for (const shortcut of SHORTCUTS) {
    if (shortcut.matches?.(event)) return shortcut;
  }
  return null;
}
