import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import type { MeSettingsResponse } from "@wlilley93/boltrig-web-sdk";

import {
  DEFAULT_CHARACTER,
  characterFromSettings,
  type CharacterId,
} from "../../character";
import { client } from "../../client";
import { needsOnboarding } from "../../onboarding";
import { BrandMark } from "../BrandMark";
import { BrandWordmark } from "../BrandWordmark";
import { CompanionStep } from "./CompanionStep";
import { NameStep } from "./NameStep";
import type { ProviderStepHandle } from "./ProviderStep";
import { ReadyStep } from "./ReadyStep";
import type { VoiceStepHandle } from "./VoiceStep";
import { useOnboardingCompletion } from "./useOnboardingCompletion";
import "./onboarding.css";

type Step = 0 | 1 | 2 | 3 | 4;
const ProviderStep = lazy(async () => {
  const module = await import("./ProviderStep");
  return { default: module.ProviderStep };
});
const VoiceStep = lazy(async () => {
  const module = await import("./VoiceStep");
  return { default: module.VoiceStep };
});

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
      .catch(() => { if (active) setAccount(null); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [initialAccount]);

  if (loading) return <OnboardingLoading />;
  if (!account) return <OnboardingUnavailable />;
  if (!needsOnboarding(account.settings)) return <>{children}</>;
  return (
    <OnboardingFlow
      account={account}
      onComplete={(settings, displayName) => setAccount({
        ...account,
        profile: { ...account.profile, display_name: displayName },
        settings,
      })}
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

function OnboardingUnavailable() {
  return (
    <main className="onboarding" aria-label="Setup unavailable">
      <div className="onboarding-aurora one" /><div className="onboarding-aurora two" />
      <section className="onboarding-panel" aria-label="Boltrig setup">
        <header className="onboarding-topbar">
          <span className="onboarding-lockup"><BrandMark className="onboarding-mark" /><BrandWordmark className="onboarding-brand" /></span>
        </header>
        <div className="onboarding-content">
          <div className="onboarding-step">
            <div className="onboarding-heading onboarding-rise">
              <p className="onboarding-kicker">Setup required</p>
            <h1>Setup couldn’t load.</h1>
              <p>Reload and try again.</p>
            </div>
            <button className="onboarding-primary" onClick={() => window.location.reload()} type="button">
              Try again
            </button>
          </div>
        </div>
      </section>
    </main>
  );
}

function OnboardingFlow({
  account,
  onComplete,
}: {
  account: MeSettingsResponse;
  onComplete: (settings: Record<string, unknown>, displayName: string) => void;
}) {
  const flow = useOnboardingFlowState(account);
  const {
    attachProviderStep, attachVoiceStep, character, completion, name, providerConnecting,
    providerReady, setCharacter, setName, setStep, step, voiceConnecting, voiceReady,
  } = flow;

  const finishSetup = () => finishOnboarding(flow);
  const continueFlow = () => continueOnboarding(flow, onComplete);

  const canContinue = onboardingCanContinue(flow);
  useOnboardingEnter(canContinue, () => void continueFlow());

  return (
    <OnboardingFrame step={step}>
      <div className="onboarding-slide" key={step}>
        <OnboardingSlide
          attachProviderStep={attachProviderStep}
          attachVoiceStep={attachVoiceStep}
          character={character}
          name={name}
          onFinish={() => void finishSetup()}
          onName={setName}
          onSelectCharacter={setCharacter}
          profile={account.profile}
          step={step}
        />
      </div>
      {completion.error && <p className="onboarding-error" role="alert">{completion.error}</p>}
      <OnboardingActions
        nameReady={Boolean(name.trim())}
        onBack={() => setStep((step - 1) as Step)}
        onContinue={() => void continueFlow()}
        providerConnecting={providerConnecting}
        providerReady={providerReady}
        saving={completion.saving}
        setupComplete={Boolean(completion.completedSettings)}
        step={step}
        voiceConnecting={voiceConnecting}
        voiceReady={voiceReady}
      />
    </OnboardingFrame>
  );
}

function useOnboardingFlowState(account: MeSettingsResponse) {
  const stored = characterFromSettings(account.settings);
  const [character, setCharacter] = useState<CharacterId>(
    stored === "jarvis" ? stored : DEFAULT_CHARACTER,
  );
  const [name, setName] = useState(account.profile.display_name?.trim() ?? "");
  const [step, setStep] = useState<Step>(0);
  const [providerReady, setProviderReady] = useState(false);
  const [providerConnecting, setProviderConnecting] = useState(false);
  const [voiceReady, setVoiceReady] = useState(false);
  const [voiceConnecting, setVoiceConnecting] = useState(false);
  const providerStepRef = useRef<ProviderStepHandle | null>(null);
  const voiceStepRef = useRef<VoiceStepHandle | null>(null);
  const completion = useOnboardingCompletion({ account, character, name });
  const attachProviderStep = useCallback((handle: ProviderStepHandle | null) => {
    providerStepRef.current = handle;
    setProviderReady(Boolean(handle));
  }, []);
  const attachVoiceStep = useCallback((handle: VoiceStepHandle | null) => {
    voiceStepRef.current = handle;
    setVoiceReady(Boolean(handle));
  }, []);
  return {
    attachProviderStep, attachVoiceStep, character, completion, name, providerConnecting,
    providerReady, providerStepRef, setCharacter, setName, setProviderConnecting, setStep,
    setVoiceConnecting, step, voiceConnecting, voiceReady, voiceStepRef,
  };
}

function onboardingCanContinue(flow: ReturnType<typeof useOnboardingFlowState>) {
  return !flow.completion.saving
    && !flow.providerConnecting
    && !flow.voiceConnecting
    && (flow.step !== 0 || Boolean(flow.name.trim()))
    && (flow.step !== 2 || flow.providerReady)
    && (flow.step !== 3 || flow.voiceReady)
    && (flow.step !== 4 || Boolean(flow.completion.completedSettings));
}

async function finishOnboarding(flow: ReturnType<typeof useOnboardingFlowState>) {
  if (await flow.completion.complete()) flow.setStep(4);
}

async function continueOnboarding(
  flow: ReturnType<typeof useOnboardingFlowState>,
  onComplete: (settings: Record<string, unknown>, displayName: string) => void,
) {
  if (flow.step === 2) {
    const providerStep = flow.providerStepRef.current;
    if (!providerStep) return;
    flow.setProviderConnecting(true);
    const completed = await providerStep.complete();
    flow.setProviderConnecting(false);
    if (!completed) return;
  }
  if (flow.step === 3) {
    const voiceStep = flow.voiceStepRef.current;
    if (!voiceStep) return;
    flow.setVoiceConnecting(true);
    const completed = await voiceStep.complete();
    flow.setVoiceConnecting(false);
    if (!completed) return;
    await finishOnboarding(flow);
    return;
  }
  if (flow.step === 4) {
    const settings = flow.completion.completedSettings;
    if (settings) onComplete(settings, flow.name.trim());
    return;
  }
  flow.setStep((flow.step + 1) as Step);
}

function OnboardingSlide({
  attachProviderStep, attachVoiceStep, character, name, onFinish, onName,
  onSelectCharacter, profile, step,
}: {
  attachProviderStep: (handle: ProviderStepHandle | null) => void;
  attachVoiceStep: (handle: VoiceStepHandle | null) => void;
  character: CharacterId;
  name: string;
  onFinish: () => void;
  onName: (name: string) => void;
  onSelectCharacter: (character: CharacterId) => void;
  profile: MeSettingsResponse["profile"];
  step: Step;
}) {
  if (step === 0) return <NameStep name={name} onName={onName} />;
  if (step === 1) return <CompanionStep selected={character} onSelect={onSelectCharacter} />;
  if (step === 2) return <Suspense fallback={<ProviderStepLoading />}><ProviderStep profile={profile} ref={attachProviderStep} /></Suspense>;
  if (step === 3) return <Suspense fallback={<VoiceStepLoading />}><VoiceStep onSkip={onFinish} profile={profile} ref={attachVoiceStep} /></Suspense>;
  return <ReadyStep character={character} userName={name.trim()} />;
}

function useOnboardingEnter(canContinue: boolean, onContinue: () => void) {
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      handleOnboardingEnter(event, canContinue, onContinue);
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  });
}

function ProviderStepLoading() {
  return (
    <div className="onboarding-step provider-step" aria-busy="true">
      <div className="onboarding-heading onboarding-rise">
        <h1>Choose your AI provider</h1>
      </div>
      <div className="onboarding-loader"><span /><span /><span /></div>
    </div>
  );
}

function VoiceStepLoading() {
  return (
    <div className="onboarding-step voice-step" aria-busy="true">
      <div className="onboarding-heading onboarding-rise">
        <p className="onboarding-kicker">Optional</p>
        <h1>Add voice</h1>
      </div>
      <div className="onboarding-loader"><span /><span /><span /></div>
    </div>
  );
}

function OnboardingActions({
  nameReady,
  onBack,
  onContinue,
  providerConnecting,
  providerReady,
  saving,
  setupComplete,
  step,
  voiceConnecting,
  voiceReady,
}: {
  nameReady: boolean;
  onBack: () => void;
  onContinue: () => void;
  providerConnecting: boolean;
  providerReady: boolean;
  saving: boolean;
  setupComplete: boolean;
  step: Step;
  voiceConnecting: boolean;
  voiceReady: boolean;
}) {
  const busy = saving || providerConnecting || voiceConnecting;
  const label = onboardingActionLabel({ providerConnecting, saving, step, voiceConnecting });
  const disabled = onboardingActionDisabled({
    busy, nameReady, providerReady, setupComplete, step, voiceReady,
  });
  return (
    <footer className="onboarding-actions onboarding-rise">
      <div className="onboarding-action-left">
        {step > 0 && step < 4
          ? <button className="onboarding-back" disabled={busy} onClick={onBack} type="button">← Back</button>
          : <span aria-hidden="true" />}
      </div>
      <button
        className="onboarding-primary"
        disabled={disabled}
        onClick={onContinue}
        type="button"
      >
        {label}
        {!busy && step < 4 ? <b aria-hidden="true">→</b> : null}
      </button>
    </footer>
  );
}

function onboardingActionLabel({ providerConnecting, saving, step, voiceConnecting }: {
  providerConnecting: boolean;
  saving: boolean;
  step: Step;
  voiceConnecting: boolean;
}) {
  if (saving) return "Finishing…";
  if (providerConnecting) return "Connecting…";
  if (voiceConnecting) return "Saving…";
  return step === 4 ? "Continue in browser" : "Continue";
}

function onboardingActionDisabled({ busy, nameReady, providerReady, setupComplete, step, voiceReady }: {
  busy: boolean;
  nameReady: boolean;
  providerReady: boolean;
  setupComplete: boolean;
  step: Step;
  voiceReady: boolean;
}) {
  return busy
    || (step === 0 && !nameReady)
    || (step === 2 && !providerReady)
    || (step === 3 && !voiceReady)
    || (step === 4 && !setupComplete);
}

function OnboardingFrame({
  children,
  step,
}: {
  children: React.ReactNode;
  step: Step;
}) {
  return (
    <main className="onboarding">
      <div className="onboarding-aurora one" /><div className="onboarding-aurora two" />
      <section className="onboarding-panel" aria-label="Boltrig setup">
        <header className="onboarding-topbar">
          <span className="onboarding-lockup"><BrandMark className="onboarding-mark" /><BrandWordmark className="onboarding-brand" /></span>
          <span className="onboarding-progress" aria-label={`Step ${step + 1} of 5`}>
            {[0, 1, 2, 3, 4].map((index) => <i className={index <= step ? "active" : ""} key={index} />)}
          </span>
          <span aria-hidden="true" />
        </header>
        <div className="onboarding-content">{children}</div>
      </section>
    </main>
  );
}

function handleOnboardingEnter(
  event: KeyboardEvent,
  canContinue: boolean,
  onContinue: () => void,
) {
  if (
    event.key !== "Enter"
    || event.repeat
    || event.altKey
    || event.ctrlKey
    || event.metaKey
    || event.shiftKey
    || event.isComposing
    || event.defaultPrevented
    || !canContinue
  ) return;
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  if (target.closest("button, [role='option'], [role='radio'], .onboarding-picker-menu")) return;
  event.preventDefault();
  onContinue();
}
