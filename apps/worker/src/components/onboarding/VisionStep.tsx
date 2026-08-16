import { forwardRef } from "react";
import type { UserProfile } from "@wlilley93/boltrig-web-sdk";

import { ProviderStepBase, type ProviderStepHandle } from "./ProviderStep";

/**
 * Optional specialist vision model. Users whose main model already accepts
 * images are told they can skip this on the provider step; everyone else is
 * invited here. Skipping advances the flow - nothing is submitted.
 */
export const VisionStep = forwardRef<
  ProviderStepHandle,
  { onSkip: () => void; profile: UserProfile }
>(function VisionStep({ onSkip, profile }, ref) {
  return (
    <ProviderStepBase
      heading="Add vision"
      kicker="Optional"
      modality="vision"
      profile={profile}
      ref={ref}
      skip={{ label: "Skip for now", onSkip }}
      sub="Save a vision model now, or skip it for later."
    />
  );
});
