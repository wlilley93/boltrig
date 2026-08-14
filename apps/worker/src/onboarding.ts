import type { CharacterId } from "./character";
import { characterToSettings } from "./character";

export const ONBOARDING_SETTING_KEY = "setup.onboarding_version";
export const ONBOARDING_VERSION = 1;

export function needsOnboarding(settings: Record<string, unknown> | undefined): boolean {
  return settings?.[ONBOARDING_SETTING_KEY] === 0;
}

export function completedOnboardingSettings(
  character: CharacterId,
): Record<string, unknown> {
  return {
    ...characterToSettings(character),
    [ONBOARDING_SETTING_KEY]: ONBOARDING_VERSION,
  };
}
