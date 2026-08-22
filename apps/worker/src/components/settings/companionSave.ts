// Saving a companion choice, split from CompactSections so the debt file
// SHRINKS while gaining the adoption affordance (the Worker structural floor
// only ratchets down). The optimistic local flip and the busy gate stay with
// the caller; everything that talks to the server lives here.

import type { CharacterId } from "../../character";
import { characterToSettings, saveCharacterLocal } from "../../character";
import type { MeSettingsResponse } from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";

type AccountLike = MeSettingsResponse | null;

/**
 * The explicit novelty affordance: the companion meets its adoption with a
 * small lift (server-throttled). Cosmetic through and through - ANY failure,
 * including a client that lacks the method, is silence; it must never be able
 * to fail or roll back the save it rides on.
 */
function announceAdoption(next: CharacterId): void {
  try {
    void client.characterAdopted(next).catch(() => {});
  } catch {
    // cosmetic: silence over an error in the settings flow
  }
}

export async function saveCompanion(
  next: CharacterId,
  previous: CharacterId,
  deps: {
    setCharacter(value: CharacterId): void;
    setMessage(text: string): void;
    setAccount(update: (current: AccountLike) => AccountLike): void;
  },
): Promise<void> {
  try {
    const result = await client.putMeSettings({ settings: characterToSettings(next) });
    if (result.status !== "ok") {
      deps.setCharacter(previous);
      saveCharacterLocal(previous);
      deps.setMessage(result.reason ?? "Your companion could not be saved.");
      return;
    }
    deps.setAccount((current) => (current
      ? { ...current, settings: { ...current.settings, ...characterToSettings(next) } }
      : current));
    if (next !== previous) announceAdoption(next);
  } catch {
    deps.setCharacter(previous);
    saveCharacterLocal(previous);
    deps.setMessage("Your companion could not be saved.");
  }
}
