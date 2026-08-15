import { forwardRef, useImperativeHandle } from "react";
import type {
  IntegrationCatalogueEntry,
  IntegrationSecretFieldContract,
  UserProfile,
} from "@wlilley93/boltrig-web-sdk";

import { SearchablePicker, type SearchableOption } from "./SearchablePicker";
import { useVoiceSetup } from "./useVoiceSetup";
import { voiceProviderDefinition } from "./voiceProviderCatalogue";

export interface VoiceStepHandle {
  complete: () => Promise<boolean>;
}

export const VoiceStep = forwardRef<VoiceStepHandle, {
  onSkip: () => void;
  profile: UserProfile;
}>(function VoiceStep({ onSkip, profile }, ref) {
  const setup = useVoiceSetup(profile);
  useImperativeHandle(ref, () => ({ complete: setup.complete }), [setup.complete]);
  const options = voiceOptions(setup.readiness?.entries ?? []);

  return (
    <div className="onboarding-step voice-step">
      <div className="onboarding-heading onboarding-rise">
        <p className="onboarding-kicker">Optional</p>
        <h1>Add voice</h1>
        <p>Save a speech service now, or skip it for later.</p>
      </div>

      <VoiceStepBody onSkip={onSkip} options={options} setup={setup} />
      {setup.message ? <p className="onboarding-status" role="status">{setup.message}</p> : null}
    </div>
  );
});

type VoiceSetup = ReturnType<typeof useVoiceSetup>;

function voiceOptions(entries: readonly IntegrationCatalogueEntry[]): SearchableOption[] {
  return entries.map((entry) => {
    const definition = voiceProviderDefinition(entry.id);
    return {
      value: entry.id,
      label: entry.label,
      detail: entry.setup_supported ? definition?.detail : "Not enabled on this server",
      info: definition?.info,
    };
  });
}

function VoiceStepBody({ onSkip, options, setup }: {
  onSkip: () => void;
  options: SearchableOption[];
  setup: VoiceSetup;
}) {
  if (!setup.readiness) {
    return <p className="onboarding-inline-note onboarding-rise" aria-busy="true">Checking voice services…</p>;
  }
  if (!setup.canConfigure) {
    return <p className="onboarding-inline-note onboarding-rise">Your organisation manages voice services.</p>;
  }
  if (options.length === 0) {
    return <p className="onboarding-inline-note onboarding-rise">No voice services are enabled on this server yet.</p>;
  }
  return <VoiceConfigurationForm onSkip={onSkip} options={options} setup={setup} />;
}

function VoiceConfigurationForm({ onSkip, options, setup }: {
  onSkip: () => void;
  options: SearchableOption[];
  setup: VoiceSetup;
}) {
  const definition = voiceProviderDefinition(setup.provider);
  return (
    <div className="onboarding-key-form voice-key-form onboarding-rise" style={{ "--onboarding-delay": "80ms" } as React.CSSProperties}>
      <SearchablePicker
        emptyText="No voice services match that search."
        label="Voice service"
        onChange={setup.selectProvider}
        options={options}
        placeholder="Choose a voice service"
        searchLabel="Search voice services"
        value={setup.provider}
      />
      {definition && (
        <div className="voice-capabilities" aria-label="Voice capabilities">
          {definition.capabilities.map((capability) => <span key={capability}>{capability}</span>)}
        </div>
      )}
      <VoiceCredentials setup={setup} />
      {setup.provider === "openai-compatible-audio" && (
        <p className="onboarding-key-note">The address must be HTTPS, reachable from the Boltrig server, and allowed by its network policy. Use the desktop app for private on-device audio.</p>
      )}
      <button className="onboarding-secondary voice-skip" disabled={setup.busy} onClick={onSkip} type="button">Skip for now</button>
    </div>
  );
}

function VoiceCredentials({ setup }: { setup: VoiceSetup }) {
  if (setup.connected) {
    return <p className="onboarding-capability voice-connected"><span aria-hidden="true">✓</span><strong>Already added</strong></p>;
  }
  if (!setup.selected?.setup_supported || !setup.selected.setup_contract) {
    return <p className="onboarding-key-note">This service has not been enabled by the Boltrig host.</p>;
  }
  return (
    <div className="voice-secret-fields">
      {setup.selected.setup_contract.fields.map((field) => (
        <VoiceField
          attach={setup.attachField}
          field={field}
          key={`${setup.provider}:${field.name}`}
          onStarted={() => setup.setStarted(true)}
        />
      ))}
    </div>
  );
}

function VoiceField({
  attach,
  field,
  onStarted,
}: {
  attach: (name: string, element: HTMLInputElement | null) => void;
  field: IntegrationSecretFieldContract;
  onStarted: () => void;
}) {
  return (
    <label>
      <span>{field.label}{field.required ? null : <em>Optional</em>}</span>
      <input
        autoComplete="off"
        inputMode={field.name === "base_url" ? "url" : undefined}
        maxLength={field.max_length}
        minLength={field.min_length}
        onChange={onStarted}
        ref={(element) => attach(field.name, element)}
        required={field.required}
        type={field.secret ? "password" : "text"}
      />
    </label>
  );
}
