import type { FormEvent } from "react";
import type {
  BifrostModelView,
  ChatModelChoice,
  ModelEndpointAuthorView,
  ModelEndpointInfo,
} from "@wlilley93/boltrig-web-sdk";

import { SettingsButton, SettingsGroup, SettingsRow, StateWord } from "./rowKit";
import {
  supportsCatalogueModalities,
  supportsCatalogueModality,
  type EndpointModality,
  type ModelReferences,
  type ModelView,
} from "./modelSettingsTypes";

export function ModelSettingsTabs({ active, onChange }: {
  active: ModelView;
  onChange(view: ModelView): void;
}) {
  return (
    <nav aria-label="Model modality" className="model-settings-tabs" role="tablist">
      {MODEL_VIEWS.map((view) => (
        <button
          aria-selected={active === view}
          className={active === view ? "is-active" : undefined}
          key={view}
          onClick={() => onChange(view)}
          role="tab"
          type="button"
        >
          {MODEL_VIEW_LABELS[view]}
        </button>
      ))}
    </nav>
  );
}

export function ModelRouteInventory({
  activeView,
  choiceProjectionAvailable,
  choices,
  endpoints,
  inventoryAvailable,
  loading,
  mutationBusy,
  onChange,
  onLifecycle,
  onPrepareRemoval,
}: {
  activeView: ModelView;
  choiceProjectionAvailable: boolean;
  choices: ChatModelChoice[];
  endpoints: ModelEndpointInfo[];
  inventoryAvailable: boolean;
  loading: boolean;
  mutationBusy: boolean;
  onChange(endpoint: ModelEndpointInfo): void;
  onLifecycle(endpoint: ModelEndpointInfo): void;
  onPrepareRemoval(endpoint: ModelEndpointInfo): void;
}) {
  return (
    <SettingsGroup
      foot={activeView === "voice"
        ? "Voice adapters resolve their credential references in the kernel. This surface never stores or displays an API key."
        : "Removing a model retires its route everywhere it is referenced, including agents and fallbacks. Its configuration is retained so it can be restored."}
      title={activeView === "voice" ? "Voice routes" : "Managed model routes"}
    >
      {loading && endpoints.length === 0 && <SettingsRow title="Loading models…" />}
      {!loading && endpoints.length === 0 && (
        <SettingsRow desc={`Add the first governed ${activeView} route below.`} title={activeView === "voice" ? "No voice routes" : `No ${activeView} models`} />
      )}
      {endpoints.map((endpoint) => (
        <ModelEndpointRow
          activeView={activeView}
          choice={choices.find((item) => item.id === endpoint.id)}
          choiceProjectionAvailable={choiceProjectionAvailable}
          endpoint={endpoint}
          inventoryAvailable={inventoryAvailable}
          key={endpoint.id}
          loading={loading}
          mutationBusy={mutationBusy}
          onChange={onChange}
          onLifecycle={onLifecycle}
          onPrepareRemoval={onPrepareRemoval}
        />
      ))}
    </SettingsGroup>
  );
}

function ModelEndpointRow({
  activeView,
  choice,
  choiceProjectionAvailable,
  endpoint,
  inventoryAvailable,
  loading,
  mutationBusy,
  onChange,
  onLifecycle,
  onPrepareRemoval,
}: {
  activeView: ModelView;
  choice?: ChatModelChoice;
  choiceProjectionAvailable: boolean;
  endpoint: ModelEndpointInfo;
  inventoryAvailable: boolean;
  loading: boolean;
  mutationBusy: boolean;
  onChange(endpoint: ModelEndpointInfo): void;
  onLifecycle(endpoint: ModelEndpointInfo): void;
  onPrepareRemoval(endpoint: ModelEndpointInfo): void;
}) {
  const presentation = endpointPresentation(endpoint, choice, choiceProjectionAvailable, activeView);
  const editable = activeView === "voice"
    ? endpoint.modalities?.includes("realtime") === true
      && ["xai", "x.ai", "grok"].includes(endpoint.kind.toLowerCase())
    : endpoint.kind === "bifrost";
  return (
    <SettingsRow
      control={(
        <div className="model-settings-actions">
          <StateWord tone={presentation.tone}>{presentation.state}</StateWord>
          <SettingsButton
            disabled={loading || !inventoryAvailable || mutationBusy || !editable}
            label="Change"
            onClick={() => onChange(endpoint)}
            title={!editable ? "This provider route cannot be rewritten in this model view." : undefined}
          />
          <SettingsButton
            disabled={loading || !inventoryAvailable || mutationBusy}
            label={endpoint.is_active ? "Remove model" : "Restore"}
            onClick={() => endpoint.is_active ? onPrepareRemoval(endpoint) : onLifecycle(endpoint)}
            tone={endpoint.is_active ? "danger" : undefined}
          />
        </div>
      )}
      desc={presentation.description}
      tech={endpoint.id}
      title={endpoint.model}
    />
  );
}

function endpointPresentation(
  endpoint: ModelEndpointInfo,
  choice: ChatModelChoice | undefined,
  projectionAvailable: boolean,
  view: ModelView,
): { description: string; state: string; tone: "green" | "amber" | "unknown" } {
  if (!endpoint.is_active) return { description: routeDescription(endpoint), state: "Removed", tone: "unknown" };
  if (view === "voice") {
    const available = endpoint.modalities?.includes("realtime")
      && ["xai", "x.ai", "grok"].includes(endpoint.kind.toLowerCase());
    return {
      description: available
        ? "Realtime voice · credential reference stays in the kernel"
        : "This stored route has no supported realtime runtime.",
      state: available ? "Configured" : "Unavailable",
      tone: available ? "green" : "amber",
    };
  }
  if (!projectionAvailable) {
    return { description: "The chat model projection could not be loaded. Endpoint state is shown separately.", state: "Status unavailable", tone: "amber" };
  }
  if (!choice) {
    return { description: "This active endpoint is not eligible for the chat switcher.", state: "Not in switcher", tone: "amber" };
  }
  if (!choice.available) {
    return { description: choice.unavailable_reason ?? "Bifrost does not currently report this model as available.", state: "Unavailable", tone: "amber" };
  }
  return { description: routeDescription(endpoint), state: "In switcher", tone: "green" };
}

function routeDescription(endpoint: ModelEndpointInfo): string {
  return `${(endpoint.modalities ?? ["text"]).join(" + ")} · standard data · ${endpoint.kind}`;
}

export function ModelRemovalDialog({ busy, endpoint, onCancel, onConfirm }: {
  busy: boolean;
  endpoint: ModelEndpointAuthorView;
  onCancel(): void;
  onConfirm(): void;
}) {
  return (
    <section aria-label="Confirm model removal" className="model-settings-removal" role="alertdialog">
      <div>
        <div className="console-section-title">Remove {endpoint.model}?</div>
        <p>This retires route <code>{endpoint.id}</code> everywhere, not only in the chat switcher. Historical task receipts and the route configuration remain.</p>
        <p>Agent references: {endpoint.references.capabilities.length > 0 ? endpoint.references.capabilities.join(", ") : "none"}. Fallback references: {endpoint.references.fallbacks.length > 0 ? endpoint.references.fallbacks.join(", ") : "none"}.</p>
      </div>
      <div className="model-settings-removal-actions">
        <SettingsButton disabled={busy} label="Cancel" onClick={onCancel} />
        <SettingsButton disabled={busy} label="Confirm removal" onClick={onConfirm} tone="danger" />
      </div>
    </section>
  );
}

export function VoiceAdapterInventory() {
  return (
    <SettingsGroup
      foot="The provider credential stays in the kernel; agent profiles receive only the governed route id."
      title="Voice route support"
    >
      <SettingsRow
        control={<StateWord tone="unknown">Supported</StateWord>}
        desc="Governed per-agent realtime routing when the channel and its server credential are enabled."
        tech="realtime · kernel credential reference"
        title="XAI realtime"
      />
    </SettingsGroup>
  );
}

export function BifrostCataloguePanel({ activeView, models, reason, status }: {
  activeView: ModelView;
  models: BifrostModelView[];
  reason: string | null;
  status: "loading" | "ok" | "unavailable";
}) {
  const count = models.filter((item) => supportsCatalogueModality(item, activeView)).length;
  return (
    <SettingsGroup
      foot="Boltrig reads this redacted catalogue on the server. Bifrost provider keys and credentials never enter the browser."
      title="Bifrost catalogue"
    >
      <SettingsRow
        control={<StateWord tone={status === "ok" ? "green" : "amber"}>{status === "loading" ? "Checking" : status === "ok" ? `${count} ${activeView} models` : "Unavailable"}</StateWord>}
        desc={status === "ok" ? "Add and change choices using the exact identifiers Bifrost currently reports." : status === "loading" ? "Reading the server-owned model catalogue." : `No model is inferred from stale data (${reason ?? "unavailable"}).`}
        title="Live model discovery"
      />
    </SettingsGroup>
  );
}

export function ModelEditorForm({
  activeView,
  busy,
  catalogueModels,
  catalogueStatus,
  endpointKind,
  hydratedExisting,
  hydratedReferences,
  id,
  inventoryAvailable,
  loading,
  modalities,
  model,
  mutationBusy,
  onAddAnother,
  onIdChange,
  onModelChange,
  onSubmit,
  onToggleModality,
}: {
  activeView: ModelView;
  busy: boolean;
  catalogueModels: BifrostModelView[];
  catalogueStatus: "loading" | "ok" | "unavailable";
  endpointKind: string;
  hydratedExisting: string | null;
  hydratedReferences: ModelReferences | null;
  id: string;
  inventoryAvailable: boolean;
  loading: boolean;
  modalities: EndpointModality[];
  model: string;
  mutationBusy: boolean;
  onAddAnother(): void;
  onIdChange(value: string): void;
  onModelChange(value: string): void;
  onSubmit(event: FormEvent<HTMLFormElement>): void;
  onToggleModality(modality: EndpointModality, checked: boolean): void;
}) {
  return (
    <form className="model-settings-form" onSubmit={onSubmit}>
      <div className="model-settings-form-head">
        <div><div className="console-section-title">{hydratedExisting ? "Change model" : "Add a model"}</div><p>{activeView === "voice" ? "Boltrig resolves the realtime provider credential in the kernel." : "Boltrig sends trusted chat routes through its server-side Bifrost path."} No provider credentials are exposed to the browser.</p></div>
        {hydratedExisting && <SettingsButton disabled={mutationBusy} label="Add another" onClick={onAddAnother} />}
      </div>
      <div className="model-settings-fields">
        <ModelIdentityFields
          activeView={activeView}
          catalogueModels={catalogueModels}
          id={id}
          idLocked={mutationBusy || Boolean(hydratedExisting)}
          locked={mutationBusy}
          modalities={modalities}
          model={model}
          onIdChange={onIdChange}
          onModelChange={onModelChange}
        />
        <ModelModalities
          activeView={activeView}
          locked={mutationBusy}
          modalities={modalities}
          onToggle={onToggleModality}
        />
      </div>
      {hydratedExisting && <HydratedRouteNotice endpointKind={endpointKind} id={hydratedExisting} references={hydratedReferences} />}
      <div className="model-settings-submit">
        <button className="primary-button" disabled={loading || !inventoryAvailable || (activeView !== "voice" && catalogueStatus !== "ok") || mutationBusy} type="submit">
          {busy ? "Requesting…" : hydratedExisting ? "Request model change" : "Request model addition"}
        </button>
      </div>
    </form>
  );
}

function ModelIdentityFields({ activeView, catalogueModels, id, idLocked, locked, modalities, model, onIdChange, onModelChange }: {
  activeView: ModelView;
  catalogueModels: BifrostModelView[];
  id: string;
  idLocked: boolean;
  locked: boolean;
  modalities: EndpointModality[];
  model: string;
  onIdChange(value: string): void;
  onModelChange(value: string): void;
}) {
  const voice = activeView === "voice";
  return (
    <>
      <label>
        <span>Internal choice ID</span>
        <input aria-label="Internal choice ID" autoComplete="off" className="field-control" disabled={idLocked} onChange={(event) => onIdChange(event.target.value)} placeholder="for example, primary-reasoning" required value={id} />
        <small>This opaque ID is stored with a chat selection, but is never shown as its model name.</small>
      </label>
      <label>
        <span>{voice ? "Exact realtime voice model name" : "Exact Bifrost model name"}</span>
        <input aria-label={voice ? "Exact realtime voice model name" : "Exact Bifrost model name"} autoComplete="off" className="field-control" disabled={locked} list={voice ? undefined : "bifrost-chat-models"} onChange={(event) => onModelChange(event.target.value)} placeholder={voice ? "grok-voice-model" : "provider/model-name"} required value={model} />
        {!voice && <datalist id="bifrost-chat-models">
          {catalogueModels.filter((item) => (
            supportsCatalogueModalities(item, modalities)
          )).map((item) => <option key={item.id} label={item.name} value={item.id} />)}
        </datalist>}
        <small>{voice ? "Use the exact model identifier supported by the kernel-owned realtime provider." : "Choose an exact identifier from the live, server-read Bifrost catalogue."}</small>
      </label>
    </>
  );
}

function ModelModalities({ activeView, locked, modalities, onToggle }: {
  activeView: ModelView;
  locked: boolean;
  modalities: EndpointModality[];
  onToggle(modality: EndpointModality, checked: boolean): void;
}) {
  const available = activeView === "voice" ? ["realtime"] as const : ["text", "vision"] as const;
  return (
    <fieldset>
      <legend>Modalities</legend>
      {available.map((modality) => (
        <label key={modality}>
          <input
            checked={modalities.includes(modality)}
            disabled={locked || activeView !== "text" || (modalities.length === 1 && modalities[0] === modality)}
            onChange={(event) => onToggle(modality, event.target.checked)}
            type="checkbox"
          />
          {modality === "text" ? "Text" : modality === "vision" ? "Vision" : "Realtime voice"}
        </label>
      ))}
    </fieldset>
  );
}

function HydratedRouteNotice({ endpointKind, id, references }: {
  endpointKind: string;
  id: string;
  references: ModelReferences | null;
}) {
  return (
    <div className="console-foot">
      <p>Saving atomically replaces the complete server record for {id}. Its existing {endpointKind} route kind and gateway topology are preserved.</p>
      <p>This route is referenced by agents: {references?.capabilities.length ? references.capabilities.join(", ") : "none"}; fallbacks: {references?.fallbacks.length ? references.fallbacks.join(", ") : "none"}. The governed approval applies to all of those uses.</p>
    </div>
  );
}

const MODEL_VIEWS = ["text", "vision", "voice"] as const;
const MODEL_VIEW_LABELS: Record<ModelView, string> = {
  text: "Text LLM",
  vision: "Vision",
  voice: "Voice",
};
