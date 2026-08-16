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

import { isCharacterId } from "@wlilley93/boltrig-web-sdk";

/** An id in the character registry. Open by design; see components/characters.ts. */
export type CharacterId = string;

/** Key inside the kernel's /v1/me/settings bag. */
export const CHARACTER_SETTING_KEY = "agent.character";

/**
 * Which of the character's skins to draw.
 *
 * A SIBLING KEY, NOT PART OF THE ID. `agent.character` is read by registration,
 * by the settings surface and by every stored setting written since the feature
 * existed; folding the skin into it as `jarvis:ultron` would make all of those
 * parse a compound value, and the id grammar is shared with plugin registration
 * -- so the first character with a colon in its name would silently become a
 * skin of something else.
 *
 * PRESENTATION ONLY, like the character it belongs to: it is not sent in Chat
 * requests and cannot alter prose or dispatch.
 */
export const CHARACTER_SKIN_SETTING_KEY = "agent.character.skin";

export const CHARACTER_CHANGE_EVENT = "boltrig:character-change";

/**
 * The Familiar, so an existing install does not change its Stage on upgrade.
 */
export const DEFAULT_CHARACTER: CharacterId = "familiar";

const STORAGE_KEY = "boltrig.character";
const SKIN_STORAGE_KEY = "boltrig.character.skin";

/** The first skin, and what a character with no variants always renders. */
export const DEFAULT_SKIN = "default";

// Shape only. Whether the id names a character anyone can draw is the
// registry's question, asked at render time.
function normalise(value: unknown): CharacterId {
  if (typeof value !== "string") return DEFAULT_CHARACTER;
  const trimmed = value.trim();
  return isCharacterId(trimmed) ? trimmed : DEFAULT_CHARACTER;
}

/**
 * Shape only, exactly as `normalise` does for the character id. WHETHER the
 * named skin exists is the registry's question and is asked at render time, so
 * a stored skin from an uninstalled variant degrades to the character's first
 * look rather than being rejected here -- the same degrade-don't-throw rule the
 * character id already follows, for the same reason.
 */
function normaliseSkin(value: unknown): string {
  if (typeof value !== "string") return DEFAULT_SKIN;
  const trimmed = value.trim();
  return isCharacterId(trimmed) ? trimmed : DEFAULT_SKIN;
}

export function loadSkin(): string {
  try {
    return normaliseSkin(localStorage.getItem(SKIN_STORAGE_KEY));
  } catch {
    return DEFAULT_SKIN;
  }
}

export function skinFromSettings(
  settings: Record<string, unknown> | undefined,
): string {
  return normaliseSkin(settings?.[CHARACTER_SKIN_SETTING_KEY]);
}

export function skinToSettings(id: string): Record<string, unknown> {
  return { [CHARACTER_SKIN_SETTING_KEY]: normaliseSkin(id) };
}

/**
 * Publishes the skin on <html> and announces it on the SAME event the character
 * uses, so a Stage mounted in another subtree swaps without a reload. One event
 * rather than two: every listener already re-reads both, and a second event
 * would double every re-render for no extra information.
 */
export function applySkin(id: string): string {
  const value = normaliseSkin(id);
  if (typeof document === "undefined") return value;
  document.documentElement.dataset.characterSkin = value;
  document.dispatchEvent(
    new CustomEvent(CHARACTER_CHANGE_EVENT, { detail: loadCharacter() }),
  );
  return value;
}

export function saveSkinLocal(id: string): string {
  const value = normaliseSkin(id);
  try {
    localStorage.setItem(SKIN_STORAGE_KEY, value);
  } catch {
    // Hardened contexts can refuse storage; applying it for this session is
    // still useful and the kernel remains authoritative.
  }
  return applySkin(value);
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
