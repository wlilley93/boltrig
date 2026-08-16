import { forwardRef, useImperativeHandle } from "react";
import type { UserProfile } from "@wlilley93/boltrig-web-sdk";

import {
  AI_PROVIDERS,
  exactModelId,
  modelAcceptsVision,
} from "./providerCatalogue";
import { SearchablePicker, type SearchableOption } from "./SearchablePicker";
import { useProviderSetup } from "./useProviderSetup";

export interface ProviderStepHandle {
  complete: () => Promise<boolean>;
}

export const ProviderStep = forwardRef<ProviderStepHandle, { profile: UserProfile }>(
function ProviderStep({ profile }, ref) {
  const setup = useProviderSetup(profile);
  useImperativeHandle(ref, () => ({ complete: setup.complete }), [setup.complete]);

  return (
    <div className="onboarding-step provider-step">
      <div className="onboarding-heading onboarding-rise">
        <h1>Choose your AI</h1>
      </div>
      {!setup.readiness
        ? <ProviderLoading />
        : setup.canAddKey
          ? <ProviderKeyForm setup={setup} />
          : <ManagedKeyNotice />}
      {setup.message && <p className="onboarding-status" role="status">{setup.message}</p>}
    </div>
  );
});

function ProviderKeyForm({ setup }: { setup: ReturnType<typeof useProviderSetup> }) {
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
        <label>
          <span>API key</span>
          <input
            aria-label="Provider API key"
            autoComplete="off"
            onChange={(event) => setup.setKeyPresent(Boolean(event.currentTarget.value))}
            ref={setup.apiKeyInput}
            required
            type="password"
          />
        </label>
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
    </div>
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
      <ExactModelField disabled={!setup.keyPresent} providerId={providerId} setup={setup} />
    </div>
  );
}

function CapabilityNotice({ vision }: { vision: boolean }) {
  return (
    <p className={`onboarding-capability ${vision ? "vision" : "text"}`} role="status">
      <span aria-hidden="true">{vision ? "◉" : "Aa"}</span>
      <strong>{vision ? "Text + images" : "Text only"}</strong>
    </p>
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
