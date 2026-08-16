import { forwardRef, useImperativeHandle } from "react";
import type { UserProfile } from "@wlilley93/boltrig-web-sdk";

import {
  AI_PROVIDERS,
  exactModelId,
  modelAcceptsVision,
  providerKeyOptional,
} from "./providerCatalogue";
import { StepHeading } from "./StepHeading";
import { SearchablePicker, type SearchableOption } from "./SearchablePicker";
import { useProviderSetup } from "./useProviderSetup";

export interface ProviderStepHandle {
  complete: () => Promise<boolean>;
}

type ProviderModality = "text" | "vision";

export const ProviderStep = forwardRef<ProviderStepHandle, { profile: UserProfile }>(
  function ProviderStep({ profile }, ref) {
    return (
      <ProviderStepBase
        heading="Choose your AI provider"
        modality="text"
        profile={profile}
        ref={ref}
      />
    );
  },
);

/**
 * The shared provider-intake body. The text step is the primary AI choice; the
 * vision step (modality "vision") is an optional specialist model reusing the
 * exact same intake, sealed once and reconciled the same way server-side.
 */
export const ProviderStepBase = forwardRef<
  ProviderStepHandle,
  {
    heading: string;
    kicker?: string;
    modality: ProviderModality;
    profile: UserProfile;
    skip?: { label: string; onSkip: () => void };
    sub?: string;
  }
>(function ProviderStepBase({ heading, kicker, modality, profile, skip, sub }, ref) {
  const setup = useProviderSetup(profile, modality);
  useImperativeHandle(ref, () => ({ complete: setup.complete }), [setup.complete]);

  return (
    <div className="onboarding-step provider-step">
      <StepHeading heading={heading} kicker={kicker} sub={sub} />
      {!setup.readiness
        ? <ProviderLoading />
        : setup.canAddKey
          ? <ProviderKeyForm setup={setup} skip={skip} />
          : <ManagedKeyNotice />}
      {setup.message && <p className="onboarding-status" role="status">{setup.message}</p>}
    </div>
  );
});

function ProviderKeyForm({
  setup,
  skip,
}: {
  setup: ReturnType<typeof useProviderSetup>;
  skip?: { label: string; onSkip: () => void };
}) {
  const provider = AI_PROVIDERS.find((entry) => entry.id === setup.provider)
    ?? AI_PROVIDERS[0];
  const selectedModel = provider?.models.find(
    (entry) => exactModelId(provider.id, entry.id) === setup.model,
  ) ?? null;
  const providerOptions: SearchableOption[] = AI_PROVIDERS.map((entry) => ({
    value: entry.id,
    label: entry.name,
    detail: entry.detail ?? (entry.id === "llama" ? "Meta’s Llama API" : entry.id),
    info: entry.info,
  }));
  const modelOptions: SearchableOption[] = (provider?.models ?? []).map((entry) => ({
    value: exactModelId(provider.id, entry.id),
    label: entry.name ?? entry.id,
    detail: modelAcceptsVision(entry) ? "Text + vision" : "Text",
  }));

  function selectProvider(providerId: string) {
    setup.setProvider(providerId);
    setup.setModel("");
    if (providerId !== "custom") setup.setBaseUrl("");
  }

  return (
    <div className="onboarding-key-form onboarding-rise" style={{ "--onboarding-delay": "80ms" } as React.CSSProperties}>
      <div className="onboarding-provider-stack">
        <SearchablePicker
          emptyText="No providers match that search."
          label="Provider"
          onChange={selectProvider}
          options={providerOptions}
          placeholder="Choose a provider"
          searchLabel="Search providers"
          value={setup.provider}
        />
        <ApiKeyField optional={provider?.keyOptional === true} setup={setup} />
        {provider?.id === "custom" ? (
          <CustomModelFields setup={setup} />
        ) : provider?.requiresBaseUrl ? (
          <OllamaModelFields providerId={provider.id} setup={setup} />
        ) : modelOptions.length === 0 ? (
          <ExactModelField disabled={!setup.keyPresent} providerId={provider.id} setup={setup} />
        ) : (
          <div className="onboarding-model-choice">
            <SearchablePicker
              disabled={!setup.keyPresent}
              emptyText="No models match that search."
              label="Model"
              onChange={setup.setModel}
              options={modelOptions}
              placeholder={setup.keyPresent ? "Choose a model" : "Enter your API key first"}
              searchLabel="Search models"
              value={setup.model}
            />
          </div>
        )}
      </div>
      {selectedModel ? <CapabilityNotice vision={modelAcceptsVision(selectedModel)} /> : null}
      {skip ? (
        <button className="onboarding-secondary provider-skip" disabled={setup.busy} onClick={skip.onSkip} type="button">
          {skip.label}
        </button>
      ) : null}
    </div>
  );
}

/** The provider API key input, and the one rule that governs it.
 *
 * Whether a key is required is a property of the PROVIDER, not of the form: a
 * self-hosted Ollama authenticates nothing, so demanding one made it
 * impossible to finish setup against a local model (FR-AIKEY-04). Keeping the
 * label, the placeholder and the `required` flag together means they cannot
 * drift into saying three different things about the same field.
 */
function ApiKeyField({ optional, setup }: {
  optional: boolean;
  setup: ReturnType<typeof useProviderSetup>;
}) {
  return (
    <label>
      <span>{optional ? "API key (optional)" : "API key"}</span>
      <input
        aria-label="Provider API key"
        // `off` is advisory and Chrome ignores it on password inputs; it was
        // filling this with a saved credential, so a keyless Ollama looked
        // like it already had a key. `new-password` is the value browsers
        // actually honour, and the two data- attributes opt out of 1Password
        // and LastPass, which ignore both.
        autoComplete="new-password"
        data-1p-ignore
        data-lpignore="true"
        onChange={(event) => setup.setKeyPresent(Boolean(event.currentTarget.value))}
        placeholder={optional ? "Leave empty for a local Ollama" : undefined}
        ref={setup.apiKeyInput}
        required={!optional}
        type="password"
      />
    </label>
  );
}

function ExactModelField({
  disabled,
  providerId,
  required = true,
  setup,
}: {
  disabled: boolean;
  providerId: string;
  required?: boolean;
  setup: ReturnType<typeof useProviderSetup>;
}) {
  const prefix = `${providerId}/`;
  const value = setup.model.startsWith(prefix) ? setup.model.slice(prefix.length) : setup.model;
  return (
    <label className="onboarding-exact-model">
      <span>Model name</span>
      <input
        aria-label="Exact model"
        autoComplete="off"
        disabled={disabled}
        onChange={(event) => setup.setModel(exactModelId(providerId, event.target.value))}
        placeholder={disabled ? "Enter your API key first" : "model-name"}
        required={required}
        value={value}
      />
    </label>
  );
}

function CustomModelFields({ setup }: { setup: ReturnType<typeof useProviderSetup> }) {
  return (
    <div className="onboarding-custom-fields">
      <label><span>API address</span><input inputMode="url" onChange={(event) => setup.setBaseUrl(event.target.value)} placeholder="https://api.example.com/v1" required value={setup.baseUrl} /></label>
      <label><span>Model name</span><input aria-label="Exact model" autoComplete="off" onChange={(event) => setup.setModel(event.target.value)} placeholder="model-name" required value={setup.model} /></label>
    </div>
  );
}

function OllamaModelFields({
  providerId,
  setup,
}: {
  providerId: string;
  setup: ReturnType<typeof useProviderSetup>;
}) {
  return (
    <div className="onboarding-custom-fields">
      <label>
        <span>API address</span>
        <input
          aria-label="Ollama API address"
          inputMode="url"
          onChange={(event) => setup.setBaseUrl(event.target.value)}
          placeholder="https://ollama.example.com/v1"
          required
          value={setup.baseUrl}
        />
      </label>
      <ExactModelField
        disabled={!setup.keyPresent && !providerKeyOptional(providerId)}
        providerId={providerId}
        setup={setup}
      />
    </div>
  );
}


function CapabilityNotice({ vision }: { vision: boolean }) {
  return (
    <div className="onboarding-capability-group">
      {vision ? (
        <p className="onboarding-capability vision" role="status">
          <span aria-hidden="true">✓</span>
          <strong>Text and Vision</strong>
        </p>
      ) : (
        <>
          <p className="onboarding-capability" role="status">
            <span aria-hidden="true">✓</span>
            <strong>Text</strong>
          </p>
          <p className="onboarding-capability no-vision" role="status">
            <span aria-hidden="true">✗</span>
            <strong>Vision</strong>
          </p>
        </>
      )}
      <p className="onboarding-key-note">
        {vision
          ? "Your model handles text and vision — you can skip the vision step."
          : "You can add a vision model on the next step."}
      </p>
    </div>
  );
}

function ManagedKeyNotice() {
  return (
    <p className="onboarding-inline-note onboarding-rise" style={{ "--onboarding-delay": "80ms" } as React.CSSProperties}>
      Your organisation manages your AI.
    </p>
  );
}

function ProviderLoading() {
  return (
    <p className="onboarding-inline-note onboarding-rise" aria-busy="true" style={{ "--onboarding-delay": "80ms" } as React.CSSProperties}>
      Checking your AI…
    </p>
  );
}
