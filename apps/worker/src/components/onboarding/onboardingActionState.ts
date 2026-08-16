/** What the single forward button says, and when it refuses.
 *
 * Pure functions over a plain object: no JSX, no hooks, nothing from the gate.
 * They encode the step machine's policy, which is easier to read - and to
 * change - away from the markup it drives.
 */
export type OnboardingStep = 0 | 1 | 2 | 3 | 4 | 5;

export function onboardingActionLabel({
  providerConnecting, saving, step, visionConnecting, voiceConnecting,
}: {
  providerConnecting: boolean;
  saving: boolean;
  step: OnboardingStep;
  visionConnecting: boolean;
  voiceConnecting: boolean;
}) {
  if (saving) return "Finishing\u2026";
  if (providerConnecting) return "Connecting\u2026";
  if (visionConnecting) return "Connecting\u2026";
  if (voiceConnecting) return "Saving\u2026";
  return step === 5 ? "Continue in browser" : "Continue";
}

export function onboardingActionDisabled({
  busy, nameReady, providerReady, setupComplete, step, visionReady, voiceReady,
}: {
  busy: boolean;
  nameReady: boolean;
  providerReady: boolean;
  setupComplete: boolean;
  step: OnboardingStep;
  visionReady: boolean;
  voiceReady: boolean;
}) {
  return busy
    || (step === 0 && !nameReady)
    || (step === 2 && !providerReady)
    || (step === 3 && !visionReady)
    || (step === 4 && !voiceReady)
    || (step === 5 && !setupComplete);
}
