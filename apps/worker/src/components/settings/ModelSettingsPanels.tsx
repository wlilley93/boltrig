import type { FormEvent } from "react";
import type {
  BifrostModelView,
  ChatModelChoice,
  ModelEndpointAuthorView,
  ModelEndpointInfo,
} from "@wlilley93/boltrig-web-sdk";

import { SettingsButton, SettingsGroup, SettingsRow, StateWord } from "./rowKit";
import {
  modelEndpointLabel,
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
      foot="Removing a model affects every agent and fallback that uses it. You can restore it later."
      title="Your models"
    >
      {loading && endpoints.length === 0 && <SettingsRow title="Loading models…" />}
      {!loading && endpoints.length === 0 && (
        <SettingsRow title={`No ${activeView} models yet`} />
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
            title={!editable ? "Managed elsewhere." : undefined}
          />
          <SettingsButton
            disabled={loading || !inventoryAvailable || mutationBusy}
            label={endpoint.is_active ? "Remove" : "Restore"}
            onClick={() => endpoint.is_active ? onPrepareRemoval(endpoint) : onLifecycle(endpoint)}
            tone={endpoint.is_active ? "danger" : undefined}
          />
        </div>
      )}
      desc={presentation.description}
      tech={endpoint.id}
      title={modelEndpointLabel(endpoint)}
    />
  );
}

function endpointPresentation(
  endpoint: ModelEndpointInfo,
  choice: ChatModelChoice | undefined,
  projectionAvailable: boolean,
  view: ModelView,
): { description?: string; state: string; tone: "green" | "amber" | "unknown" } {
  if (!endpoint.is_active) return { description: routeDescription(endpoint), state: "Removed", tone: "unknown" };
  if (view === "voice") {
    const available = endpoint.modalities?.includes("realtime")
      && ["xai", "x.ai", "grok"].includes(endpoint.kind.toLowerCase());
    return {
      description: available ? "Live voice" : undefined,
      state: available ? "Ready" : "Unavailable",
      tone: available ? "green" : "amber",
    };
  }
  if (!projectionAvailable) {
    return { description: "Couldn’t check availability.", state: "Unknown", tone: "amber" };
  }
  if (!choice) {
    return { description: undefined, state: "Unavailable", tone: "amber" };
  }
  if (!choice.available) {
    return { description: undefined, state: "Unavailable", tone: "amber" };
  }
  return { description: routeDescription(endpoint), state: "Ready", tone: "green" };
}

function routeDescription(endpoint: ModelEndpointInfo): string {
  return (endpoint.modalities ?? ["text"])
    .map((item) => item === "realtime" ? "Live voice" : `${item[0]?.toUpperCase()}${item.slice(1)}`)
    .join(" + ");
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
        <div className="console-section-title">Remove {modelEndpointLabel(endpoint)}?</div>
        <p>This removes it everywhere it is used. You can restore it later.</p>
        {(endpoint.references.capabilities.length > 0 || endpoint.references.fallbacks.length > 0) && (
          <p>Used by: {[...endpoint.references.capabilities, ...endpoint.references.fallbacks].join(", ")}.</p>
        )}
      </div>
      <div className="model-settings-removal-actions">
        <SettingsButton disabled={busy} label="Cancel" onClick={onCancel} />
        <SettingsButton disabled={busy} label="Confirm removal" onClick={onConfirm} tone="danger" />
      </div>
    </section>
  );
}

export function BifrostCataloguePanel({ activeView, models, status }: {
  activeView: ModelView;
  models: BifrostModelView[];
  status: "loading" | "ok" | "unavailable";
}) {
  const count = models.filter((item) => supportsCatalogueModality(item, activeView)).length;
  return (
    <SettingsGroup
      title="Available models"
    >
      <SettingsRow
        control={<StateWord tone={status === "ok" ? "green" : "amber"}>{status === "loading" ? "Checking" : status === "ok" ? `${count} ${activeView} models` : "Unavailable"}</StateWord>}
        desc={status === "loading" ? "Checking…" : status === "unavailable" ? "Try again later." : undefined}
        title="Live list"
      />
    </SettingsGroup>
  );
}

export function ModelEditorForm({
  activeView,
  busy,
  catalogueModels,
  catalogueStatus,
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
        <div><div className="console-section-title">{hydratedExisting ? "Change model" : "Add model"}</div><p>Keys stay private.</p></div>
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
        {activeView === "text" && (
          <ModelModalities
            locked={mutationBusy}
            modalities={modalities}
            onToggle={onToggleModality}
          />
        )}
      </div>
      {hydratedExisting && <HydratedRouteNotice references={hydratedReferences} />}
      <div className="model-settings-submit">
        <button className="primary-button" disabled={loading || !inventoryAvailable || (activeView !== "voice" && catalogueStatus !== "ok") || mutationBusy} type="submit">
          {busy ? "Saving…" : hydratedExisting ? "Save changes" : "Add model"}
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
        <span>Route name</span>
        <input aria-label="Route name" autoComplete="off" className="field-control" disabled={idLocked} onChange={(event) => onIdChange(event.target.value)} placeholder="primary-model" required value={id} />
      </label>
      <label>
        <span>Model</span>
        <input aria-label="Model" autoComplete="off" className="field-control" disabled={locked} list={voice ? undefined : "available-chat-models"} onChange={(event) => onModelChange(event.target.value)} placeholder={voice ? "Voice model" : "Provider/model"} required value={model} />
        {!voice && <datalist id="available-chat-models">
          {catalogueModels.filter((item) => (
            supportsCatalogueModalities(item, modalities)
          )).map((item) => <option key={item.id} label={item.name} value={item.id} />)}
        </datalist>}
      </label>
    </>
  );
}

function ModelModalities({ locked, modalities, onToggle }: {
  locked: boolean;
  modalities: EndpointModality[];
  onToggle(modality: EndpointModality, checked: boolean): void;
}) {
  const available = ["text", "vision"] as const;
  return (
    <fieldset>
      <legend>Capabilities</legend>
      {available.map((modality) => (
        <label key={modality}>
          <input
            checked={modalities.includes(modality)}
            disabled={locked || (modalities.length === 1 && modalities[0] === modality)}
            onChange={(event) => onToggle(modality, event.target.checked)}
            type="checkbox"
          />
          {modality === "text" ? "Text" : "Vision"}
        </label>
      ))}
    </fieldset>
  );
}

function HydratedRouteNotice({ references }: {
  references: ModelReferences | null;
}) {
  return (
    <div className="console-foot">
      <p>Used by agents: {references?.capabilities.length ? references.capabilities.join(", ") : "none"}. Fallback for: {references?.fallbacks.length ? references.fallbacks.join(", ") : "none"}.</p>
    </div>
  );
}

const MODEL_VIEWS = ["text", "vision", "voice"] as const;
const MODEL_VIEW_LABELS: Record<ModelView, string> = {
  text: "Text",
  vision: "Vision",
  voice: "Voice",
};
