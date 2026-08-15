import { useCallback, useRef, useState } from "react";
import type { MeSettingsResponse } from "@wlilley93/boltrig-web-sdk";

import { saveCharacterLocal, type CharacterId } from "../../character";
import { client } from "../../client";
import { completedOnboardingSettings } from "../../onboarding";

export function useOnboardingCompletion({
  account,
  character,
  name,
}: {
  account: MeSettingsResponse;
  character: CharacterId;
  name: string;
}) {
  const [completedSettings, setCompletedSettings] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const inFlight = useRef(false);

  const complete = useCallback(async () => {
    if (inFlight.current) return false;
    inFlight.current = true;
    setSaving(true);
    setError("");
    const settings = completedOnboardingSettings(character);
    try {
      const profileResult = await client.updateMeProfile({ display_name: name.trim() });
      if (profileResult.status !== "ok") {
        throw new Error(profileResult.reason ?? profileResult.status);
      }
      const result = await client.putMeSettings({ settings });
      if (result.status !== "ok") throw new Error(result.reason ?? result.status);
      saveCharacterLocal(character);
      setCompletedSettings({ ...account.settings, ...settings });
      return true;
    } catch {
      setError("Setup could not be saved. Nothing was inferred; please try again.");
      return false;
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  }, [account.settings, character, name]);

  return { complete, completedSettings, error, saving };
}
