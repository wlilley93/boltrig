// Which body is shown on the Stage. It has its own persisted setting and change
// event because it switches renderer families rather than restyling one theme.
// The current production contract is presentational: this value is not sent in
// Chat requests and does not alter response prose or dispatch.
//
// THIS MODULE NAMES NO CHARACTER BUT THE DEFAULT. The id is an open string
// validated only for shape, because characters are a registry (see
// components/characters.ts) that a plugin can add to without editing boltrig.
// A stored id whose character is not registered — an uninstalled plugin, or a
// build that never shipped it — resolves to the default at render time rather
// than being rejected here, so removing a character degrades the Stage instead
// of breaking the setting.

/** An id in the character registry. Open by design; see components/characters.ts. */
export type CharacterId = string;

/** Key inside the kernel's /v1/me/settings bag. */
export const CHARACTER_SETTING_KEY = "agent.character";

export const CHARACTER_CHANGE_EVENT = "boltrig:character-change";

/**
 * The Familiar, so an existing install does not change its Stage on upgrade.
 */
export const DEFAULT_CHARACTER: CharacterId = "familiar";

const STORAGE_KEY = "boltrig.character";

// Shape only. Whether the id names a character anyone can draw is the
// registry's question, asked at render time.
function normalise(value: unknown): CharacterId {
  if (typeof value !== "string") return DEFAULT_CHARACTER;
  const trimmed = value.trim();
  return /^[a-z][a-z0-9-]{0,63}$/.test(trimmed) ? trimmed : DEFAULT_CHARACTER;
}

export function loadCharacter(): CharacterId {
  try {
    return normalise(localStorage.getItem(STORAGE_KEY));
  } catch {
    return DEFAULT_CHARACTER;
  }
}

export function characterFromSettings(
  settings: Record<string, unknown> | undefined,
): CharacterId {
  return normalise(settings?.[CHARACTER_SETTING_KEY]);
}

export function characterToSettings(id: CharacterId): Record<string, unknown> {
  return { [CHARACTER_SETTING_KEY]: normalise(id) };
}

/**
 * Publishes the choice on <html> so CSS can respond, and announces it so a
 * Stage mounted in another subtree swaps without a reload.
 */
export function applyCharacter(id: CharacterId): CharacterId {
  const value = normalise(id);
  if (typeof document === "undefined") return value;
  document.documentElement.dataset.character = value;
  document.dispatchEvent(
    new CustomEvent(CHARACTER_CHANGE_EVENT, { detail: value }),
  );
  return value;
}

export function saveCharacterLocal(id: CharacterId): CharacterId {
  const value = normalise(id);
  try {
    localStorage.setItem(STORAGE_KEY, value);
  } catch {
    // Hardened contexts can refuse storage. Applying it for this session is
    // still useful, and the kernel remains authoritative.
  }
  return applyCharacter(value);
}

export function bootstrapCharacter(): CharacterId {
  return applyCharacter(loadCharacter());
}
