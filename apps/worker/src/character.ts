// Which body is shown on the Stage. It has its own persisted setting and change
// event because it switches renderer families rather than restyling one theme.
// The current production contract is presentational: this value is not sent in
// Chat requests and does not alter response prose or dispatch.

export type CharacterId = "familiar" | "jarvis";

export const CHARACTER_IDS: readonly CharacterId[] = ["familiar", "jarvis"] as const;

/** Key inside the kernel's /v1/me/settings bag. */
export const CHARACTER_SETTING_KEY = "agent.character";

export const CHARACTER_CHANGE_EVENT = "boltrig:character-change";

/**
 * The Familiar, so an existing install does not change its Stage on upgrade.
 */
export const DEFAULT_CHARACTER: CharacterId = "familiar";

const STORAGE_KEY = "boltrig.character";

function normalise(value: unknown): CharacterId {
  return typeof value === "string" && CHARACTER_IDS.includes(value as CharacterId)
    ? (value as CharacterId)
    : DEFAULT_CHARACTER;
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
