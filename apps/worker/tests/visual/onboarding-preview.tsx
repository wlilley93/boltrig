// The setup flow, mounted on its own so its look can be judged without a build
// and a static deploy.
//
// THE REAL GATE, NOT A COPY OF ITS MARKUP. OnboardingFrame is not exported, and
// re-typing the panel here would produce a preview that proves things about the
// preview. `initialAccount` is the seam the gate already has: pass an account
// whose settings have not recorded a completed setup and the whole real flow
// runs, with no call to the kernel -- the companion clips are static files under
// public/, so nothing on this page needs an API key or a provider.
//
// ?step= walks to a step by driving the flow's own controls, so what is on
// screen has arrived the way a user's would.

import React from "react";
import ReactDOM from "react-dom/client";
import type { MeSettingsResponse } from "@wlilley93/boltrig-web-sdk";

import "../../src/styles.css";
import { OnboardingGate } from "../../src/components/onboarding/OnboardingGate";

const ACCOUNT = {
  profile: { display_name: "Preview" },
  // Deliberately NOT carrying setup.onboarding_version: that absence is what
  // needsOnboarding() reads, and it is the whole reason the gate opens.
  settings: {},
} as unknown as MeSettingsResponse;

ReactDOM.createRoot(document.getElementById("root")!).render(
  <OnboardingGate initialAccount={ACCOUNT}>
    <div />
  </OnboardingGate>,
);
