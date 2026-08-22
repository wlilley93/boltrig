/**
 * Presentation-only shell preferences.
 *
 * There is deliberately no `shell-v2` flag here. Worker has one shell
 * implementation, so a boolean could neither canary a second implementation
 * nor provide a real rollback path. The rollout boundary is structural instead:
 * Shell delegates navigation and task history to the components in this
 * directory, while this module is the sole persistence adapter for their local
 * preferences.
 *
 * The versioned value is mirrored to the legacy pin key. A newer build can
 * migrate the legacy array forward, and an older build can still read changes
 * made after rollback. Shell presentation state never becomes server policy.
 */

export const SHELL_PREFERENCES_V1_KEY = "boltrig.shell-preferences.v1";
export const LEGACY_PINNED_CONVERSATIONS_KEY = "boltrig-worker-pinned-conversations";
export const SHELL_ORGANIZE_MODE_KEY = "boltrig.sidebar-organize.v1";
export type ShellOrganizeMode = "project" | "agent" | "list";

interface StoredShellPreferencesV1 {
  schema_version: 1;
  pinned_conversation_ids: string[];
}

export interface ShellPreferences {
  pinnedConversationIds: string[];
}

export function loadShellPreferences(): ShellPreferences {
  const stored = readStoredPreferences();
  if (stored) {
    const value = toPreferences(stored);
    // Keep the downgrade reader current even when this install was first
    // written by the versioned shell.
    mirrorLegacyPins(value.pinnedConversationIds);
    return value;
  }

  const migrated = {
    pinnedConversationIds: readLegacyPins(),
  };
  // Loading is the migration point. Both writes are best-effort, matching the
  // existing behaviour in hardened contexts where localStorage is unavailable.
  persistShellPreferences(migrated);
  return migrated;
}

export function persistShellPreferences(value: ShellPreferences): ShellPreferences {
  const normalised = normalisePreferences(value);
  const stored: StoredShellPreferencesV1 = {
    schema_version: 1,
    pinned_conversation_ids: normalised.pinnedConversationIds,
  };
  try {
    localStorage.setItem(SHELL_PREFERENCES_V1_KEY, JSON.stringify(stored));
  } catch {
    // The in-memory React state remains useful when storage is unavailable.
  }
  mirrorLegacyPins(normalised.pinnedConversationIds);
  return normalised;
}

export function loadShellOrganizeMode(): ShellOrganizeMode {
  try {
    const value = localStorage.getItem(SHELL_ORGANIZE_MODE_KEY);
    return value === "agent" || value === "list" ? value : "project";
  } catch {
    return "project";
  }
}

export function persistShellOrganizeMode(mode: ShellOrganizeMode): ShellOrganizeMode {
  try {
    localStorage.setItem(SHELL_ORGANIZE_MODE_KEY, mode);
  } catch {
    // The in-memory React state remains useful when storage is unavailable.
  }
  return mode;
}

function readStoredPreferences(): StoredShellPreferencesV1 | null {
  try {
    const raw = localStorage.getItem(SHELL_PREFERENCES_V1_KEY);
    if (!raw) return null;
    const value: unknown = JSON.parse(raw);
    if (!isRecord(value) || value.schema_version !== 1) return null;
    return {
      schema_version: 1,
      pinned_conversation_ids: normaliseConversationIds(value.pinned_conversation_ids),
    };
  } catch {
    return null;
  }
}

function readLegacyPins(): string[] {
  try {
    return normaliseConversationIds(JSON.parse(
      localStorage.getItem(LEGACY_PINNED_CONVERSATIONS_KEY) ?? "[]",
    ));
  } catch {
    return [];
  }
}

function mirrorLegacyPins(ids: string[]): void {
  try {
    localStorage.setItem(LEGACY_PINNED_CONVERSATIONS_KEY, JSON.stringify(ids));
  } catch {
    // Downgrade compatibility is best-effort in storage-restricted contexts.
  }
}

function toPreferences(value: StoredShellPreferencesV1): ShellPreferences {
  return {
    pinnedConversationIds: [...value.pinned_conversation_ids],
  };
}

function normalisePreferences(value: ShellPreferences): ShellPreferences {
  return {
    pinnedConversationIds: normaliseConversationIds(value.pinnedConversationIds),
  };
}

function normaliseConversationIds(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.filter(
    (id): id is string => typeof id === "string" && id.length > 0,
  ))];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
