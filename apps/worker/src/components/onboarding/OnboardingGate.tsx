import { useEffect, useState } from "react";
import type { MeSettingsResponse } from "@wlilley93/boltrig-web-sdk";

import {
  DEFAULT_CHARACTER,
  characterFromSettings,
  saveCharacterLocal,
  type CharacterId,
} from "../../character";
import { client } from "../../client";
import {
  completedOnboardingSettings,
  needsOnboarding,
} from "../../onboarding";
import { CompanionStep } from "./CompanionStep";
import { ProviderStep } from "./ProviderStep";
import { ReadyStep } from "./ReadyStep";
import "./onboarding.css";

type Step = 0 | 1 | 2;

export function OnboardingGate({
  children,
  initialAccount,
}: {
  children: React.ReactNode;
  initialAccount?: MeSettingsResponse | null;
}) {
  const [account, setAccount] = useState(initialAccount ?? null);
  const [loading, setLoading] = useState(!initialAccount);

  useEffect(() => {
    if (initialAccount) {
      setAccount(initialAccount);
      setLoading(false);
      return;
    }
    let active = true;
    void client.meSettings()
      .then((result) => { if (active) setAccount(result); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [initialAccount]);

  if (loading) return <OnboardingLoading />;
  if (!account || !needsOnboarding(account.settings)) return <>{children}</>;
  return (
    <OnboardingFlow
      account={account}
      onComplete={(settings) => setAccount({ ...account, settings })}
    />
  );
}

function OnboardingLoading() {
  return (
    <main className="onboarding loading" aria-busy="true" aria-label="Preparing setup">
      <div className="onboarding-loader"><span /><span /><span /></div>
    </main>
  );
}

function OnboardingFlow({
  account,
  onComplete,
}: {
  account: MeSettingsResponse;
  onComplete: (settings: Record<string, unknown>) => void;
}) {
  const stored = characterFromSettings(account.settings);
  const [character, setCharacter] = useState<CharacterId>(
    stored === "jarvis" ? stored : DEFAULT_CHARACTER,
  );
  const [step, setStep] = useState<Step>(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function finish() {
    setSaving(true);
    setError("");
    const settings = completedOnboardingSettings(character);
    try {
      const result = await client.putMeSettings({ settings });
      if (result.status !== "ok") throw new Error(result.reason ?? result.status);
      saveCharacterLocal(character);
      onComplete({ ...account.settings, ...settings });
    } catch {
      setError("Setup could not be saved. Nothing was inferred; please try again.");
      setSaving(false);
    }
  }

  return (
    <OnboardingFrame step={step} onBack={() => setStep((step - 1) as Step)}>
      <div className="onboarding-slide" key={step}>
        {step === 0 && <CompanionStep selected={character} onSelect={setCharacter} />}
        {step === 1 && <ProviderStep profile={account.profile} />}
        {step === 2 && <ReadyStep character={character} />}
      </div>
      {error && <p className="onboarding-error" role="alert">{error}</p>}
      <footer className="onboarding-actions onboarding-rise">
        <span>{step === 1 ? "Provider setup is optional." : ""}</span>
        <button
          className="onboarding-primary"
          disabled={saving}
          onClick={() => step === 2 ? void finish() : setStep((step + 1) as Step)}
          type="button"
        >
          {saving ? "Saving…" : step === 2 ? "Start using Boltrig" : "Continue"}
          {!saving && step < 2 ? <b aria-hidden="true">→</b> : null}
        </button>
      </footer>
    </OnboardingFrame>
  );
}

function OnboardingFrame({
  children,
  step,
  onBack,
}: {
  children: React.ReactNode;
  step: Step;
  onBack: () => void;
}) {
  return (
    <main className="onboarding">
      <div className="onboarding-aurora one" /><div className="onboarding-aurora two" />
      <section className="onboarding-panel" aria-label="Boltrig setup">
        <header className="onboarding-topbar">
          <span className="onboarding-brand"><i>ϟ</i> Boltrig</span>
          <span className="onboarding-progress" aria-label={`Step ${step + 1} of 3`}>
            {[0, 1, 2].map((index) => <i className={index <= step ? "active" : ""} key={index} />)}
          </span>
          <button className="onboarding-back" disabled={step === 0} onClick={onBack} type="button">← Back</button>
        </header>
        <div className="onboarding-content">{children}</div>
      </section>
    </main>
  );
}
