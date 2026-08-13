import { useEffect, useState } from "react";
import type {
  BifrostModelView,
  ChatModelChoice,
  InvokeRequest,
  InvokeResult,
  ModelEndpointAuthorView,
  ModelEndpointInfo,
  ModelEndpointLifecycleResponse,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import {
  ExactApprovalFinalizer,
  governedResultReason,
  useExactApprovalFinalizer,
} from "../ExactApprovalFinalizer";
import {
  BifrostCataloguePanel,
  ModelEditorForm,
  ModelRemovalDialog,
  ModelRouteInventory,
  ModelSettingsTabs,
  VoiceAdapterInventory,
} from "./ModelSettingsPanels";
import { SectionHead } from "./SectionHead";
import {
  supportsCatalogueModalities,
  supportsEndpointView,
  type EndpointModality,
  type ModelReferences,
  type ModelView,
} from "./modelSettingsTypes";
import "./model-settings.css";

type ModelMutation =
  | {
    kind: "upsert";
    request: InvokeRequest;
    params: Record<string, unknown>;
    hydratedExisting: string | null;
    hydratedReferences: ModelReferences | null;
    hydratedSnapshot: ModelEndpointAuthorView | null;
  }
  | {
    kind: "retire" | "restore";
    endpoint: ModelEndpointInfo;
  };

function modelParams(fields: {
  id: string;
  kind: string;
  model: string;
  baseUrl: string;
  fallback: string;
  modalities: EndpointModality[];
}): Record<string, unknown> {
  return {
    id: fields.id.trim(),
    kind: fields.kind.trim() || "bifrost",
    model: fields.model.trim(),
    base_url: fields.baseUrl.trim() || undefined,
    fallback: fields.fallback.trim() || undefined,
    data_class: "standard",
    modalities: fields.modalities,
  };
}

function sameRouteInput(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function initialRoute(view: ModelView): { kind: string; modalities: EndpointModality[] } {
  if (view === "voice") return { kind: "xai", modalities: ["realtime"] };
  return { kind: "bifrost", modalities: [view] };
}

function sameReferences(
  left: ModelReferences | null,
  right: ModelReferences | null,
): boolean {
  return sameRouteInput(left, right);
}

function sameEndpointState(left: ModelEndpointInfo, right: ModelEndpointInfo): boolean {
  return left.id === right.id
    && left.kind === right.kind
    && left.model === right.model
    && left.data_class === right.data_class
    && left.revision === right.revision
    && left.is_active === right.is_active
    && left.status === right.status
    && sameRouteInput(left.modalities ?? ["text"], right.modalities ?? ["text"]);
}

function sameHydratedSnapshot(
  left: ModelEndpointAuthorView | null,
  right: ModelEndpointAuthorView | null,
): boolean {
  if (left === null || right === null) return left === right;
  return sameEndpointState(left, right)
    && left.base_url === right.base_url
    && left.fallback === right.fallback
    && sameReferences(left.references, right.references);
}

/** A settings-sized view of the governed model endpoint authoring route.
 * The browser never contacts Bifrost or receives its credentials. Adding and
 * changing use the existing server-side upsert verb; "Remove" is the
 * recoverable endpoint-retirement operation required by the kernel. */
export function ModelSettingsSection({ head = true }: { head?: boolean }) {
  const [allEndpoints, setAllEndpoints] = useState<ModelEndpointInfo[]>([]);
  const [activeView, setActiveView] = useState<ModelView>("text");
  const [choices, setChoices] = useState<ChatModelChoice[]>([]);
  const [choiceProjectionAvailable, setChoiceProjectionAvailable] = useState(false);
  const [catalogueModels, setCatalogueModels] = useState<BifrostModelView[]>([]);
  const [catalogueStatus, setCatalogueStatus] = useState<"loading" | "ok" | "unavailable">("loading");
  const [catalogueReason, setCatalogueReason] = useState<string | null>(null);
  const [pendingRemoval, setPendingRemoval] = useState<ModelEndpointAuthorView | null>(null);
  const [id, setId] = useState("");
  const [endpointKind, setEndpointKind] = useState("bifrost");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [fallback, setFallback] = useState("");
  const [modalities, setModalities] = useState<EndpointModality[]>(["text"]);
  const [hydratedExisting, setHydratedExisting] = useState<string | null>(null);
  const [hydratedReferences, setHydratedReferences] = useState<ModelReferences | null>(null);
  const [hydratedSnapshot, setHydratedSnapshot] = useState<ModelEndpointAuthorView | null>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [inventoryAvailable, setInventoryAvailable] = useState(false);
  const [busy, setBusy] = useState(false);
  const endpoints = allEndpoints.filter(
    (endpoint) => endpoint.data_class === "standard" && supportsEndpointView(endpoint, activeView),
  );

  const finalizer = useExactApprovalFinalizer<
    ModelMutation,
    InvokeResult | ModelEndpointLifecycleResponse
  >({
    isCurrent: (input) => {
      if (input.kind === "upsert") {
        return input.hydratedExisting === hydratedExisting
          && sameReferences(input.hydratedReferences, hydratedReferences)
          && sameHydratedSnapshot(input.hydratedSnapshot, hydratedSnapshot)
          && sameRouteInput(input.params, modelParams({
            id,
            kind: endpointKind,
            model,
            baseUrl,
            fallback,
            modalities,
          }));
      }
      const current = endpoints.find((endpoint) => endpoint.id === input.endpoint.id);
      return current !== undefined && sameEndpointState(current, input.endpoint);
    },
    replay: async (input, approvalId) => {
      if (input.kind === "upsert") {
        if (input.hydratedSnapshot !== null) {
          let current: ModelEndpointAuthorView;
          try {
            current = (await client.modelEndpoint(input.hydratedSnapshot.id)).endpoint;
          } catch {
            return { status: "error", reason: "model_endpoint_snapshot_unavailable" };
          }
          if (!sameHydratedSnapshot(input.hydratedSnapshot, current)) {
            return { status: "error", reason: "model_endpoint_snapshot_changed" };
          }
        }
        return client.invoke({ ...input.request, approval_id: approvalId });
      }
      return input.kind === "retire"
        ? client.retireModelEndpoint(input.endpoint.id, approvalId)
        : client.restoreModelEndpoint(input.endpoint.id, approvalId);
    },
    onApplied: async (_result, input) => {
      await refresh(false);
      setMessage(input.kind === "upsert"
        ? "Model saved."
        : input.kind === "retire"
          ? `${input.endpoint.model} was retired from model routing.`
          : `${input.endpoint.model} was restored to model routing.`);
    },
    onRefused: (result) => {
      setMessage(governedResultReason(result, "The approved model change was refused."));
    },
    onUncertain: async () => {
      await refresh(false);
      setMessage("Canonical model state was refreshed; no change is inferred.");
    },
  });
  const mutationBusy = busy || finalizer.busy;

  async function refresh(invalidate = true) {
    if (invalidate) finalizer.invalidate();
    setLoading(true);
    try {
      const [inventory, switcher, catalogue] = await Promise.all([
        client.modelEndpoints(),
        client.chatModelChoices().catch(() => null),
        client.bifrostModels().catch(() => null),
      ]);
      setAllEndpoints(inventory.endpoints);
      setInventoryAvailable(true);
      setChoices(switcher?.choices ?? []);
      setChoiceProjectionAvailable(switcher !== null);
      if (catalogue?.status === "ok") {
        setCatalogueModels(catalogue.models);
        setCatalogueStatus("ok");
        setCatalogueReason(null);
      } else {
        setCatalogueModels([]);
        setCatalogueStatus("unavailable");
        setCatalogueReason(catalogue?.reason ?? "gateway_unavailable");
      }
      if (hydratedExisting) {
        const current = inventory.endpoints.find((endpoint) => endpoint.id === hydratedExisting);
        if (current) {
          const detail = await client.modelEndpoint(current.id);
          setId(detail.endpoint.id);
          setEndpointKind(detail.endpoint.kind);
          setModel(detail.endpoint.model);
          setBaseUrl(detail.endpoint.base_url ?? "");
          setFallback(detail.endpoint.fallback ?? "");
          setModalities((detail.endpoint.modalities ?? ["text"]).filter(
            (item): item is EndpointModality =>
              ["text", "vision", "stt", "tts", "realtime"].includes(item),
          ));
          setHydratedExisting(detail.endpoint.id);
          setHydratedReferences(detail.endpoint.references);
          setHydratedSnapshot(detail.endpoint);
        } else {
          clearForm(false);
        }
      }
      setMessage((current) => (
        current === "Model inventory is unavailable." ? "" : current
      ));
    } catch {
      setInventoryAvailable(false);
      setChoiceProjectionAvailable(false);
      setCatalogueModels([]);
      setCatalogueStatus("unavailable");
      setCatalogueReason("gateway_unavailable");
      setMessage("Model inventory is unavailable.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh(false);
  }, []);

  async function edit(endpoint: ModelEndpointInfo) {
    finalizer.invalidate();
    setMessage("");
    setHydratedExisting(null);
    setHydratedReferences(null);
    setHydratedSnapshot(null);
    try {
      const detail = await client.modelEndpoint(endpoint.id);
      if (
        detail.endpoint.data_class !== "standard"
        || !supportsEndpointView(detail.endpoint, activeView)
      ) {
        setMessage("This route is not part of the selected model view.");
        return;
      }
      const editableKind = activeView === "voice"
        ? ["xai", "x.ai", "grok"].includes(detail.endpoint.kind.toLowerCase())
          && detail.endpoint.modalities?.includes("realtime") === true
        : detail.endpoint.kind === "bifrost";
      if (!editableKind) {
        setMessage(
          "This route is managed by another provider topology and cannot be rewritten here.",
        );
        return;
      }
      setId(detail.endpoint.id);
      setEndpointKind(detail.endpoint.kind);
      setModel(detail.endpoint.model);
      setBaseUrl(detail.endpoint.base_url ?? "");
      setFallback(detail.endpoint.fallback ?? "");
      setModalities((detail.endpoint.modalities ?? ["text"]).filter(
        (item): item is EndpointModality =>
          ["text", "vision", "stt", "tts", "realtime"].includes(item),
      ));
      setHydratedExisting(detail.endpoint.id);
      setHydratedReferences(detail.endpoint.references);
      setHydratedSnapshot(detail.endpoint);
    } catch {
      setMessage("The complete model record could not be loaded, so it was not changed.");
    }
  }

  function clearForm(invalidate = true, view = activeView) {
    if (invalidate) finalizer.invalidate();
    const initial = initialRoute(view);
    setId("");
    setEndpointKind(initial.kind);
    setModel("");
    setBaseUrl("");
    setFallback("");
    setModalities(initial.modalities);
    setHydratedExisting(null);
    setHydratedReferences(null);
    setHydratedSnapshot(null);
  }

  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cleanId = id.trim();
    const cleanModel = model.trim();
    if (!cleanId || !cleanModel) return;
    if (loading || !inventoryAvailable) {
      setMessage("Wait for the complete model inventory before adding a route.");
      return;
    }
    if (activeView !== "voice" && catalogueStatus !== "ok") {
      setMessage("Bifrost model discovery is unavailable, so this model cannot be verified or changed.");
      return;
    }
    const discovered = catalogueModels.find((item) => item.id === cleanModel);
    if (activeView !== "voice" && (
      !discovered || !supportsCatalogueModalities(discovered, modalities)
    )) {
      const required = modalities
        .filter((item) => item === "text" || item === "vision")
        .join(" + ");
      setMessage(
        `Choose an exact Bifrost model that advertises every selected modality (${required}).`,
      );
      return;
    }
    if (
      allEndpoints.some((endpoint) => endpoint.id === cleanId)
      && hydratedExisting !== cleanId
    ) {
      setMessage("That ID already belongs to another model endpoint and cannot be replaced here.");
      return;
    }
    const params = modelParams({
      id,
      kind: endpointKind,
      model,
      baseUrl,
      fallback,
      modalities,
    });
    const input: ModelMutation = {
      kind: "upsert",
      hydratedExisting,
      hydratedReferences,
      hydratedSnapshot,
      params,
      request: {
        noun: "control",
        verb: "control.model_endpoint.upsert",
        idempotency_key: crypto.randomUUID(),
        params,
      },
    };
    setBusy(true);
    setMessage("");
    try {
      const result = await client.invoke(input.request);
      if (finalizer.begin(input, result, "Chat model change")) {
        setMessage("This model change is waiting for approval in the originating chat.");
      } else if (
        result.status === "denied"
        || result.status === "error"
        || result.status === "unavailable"
      ) {
        setMessage(`Not changed: ${result.reason ?? "the kernel refused the request"}.`);
      } else if (result.status === "degraded") {
        await refresh(false);
        setMessage("Canonical model state was refreshed after a degraded response; no save is inferred.");
      } else {
        setMessage("Model saved.");
        await refresh(false);
      }
    } catch {
      setMessage("The model was not changed.");
    } finally {
      setBusy(false);
    }
  }

  async function changeLifecycle(endpoint: ModelEndpointInfo) {
    finalizer.invalidate();
    setBusy(true);
    setMessage("");
    const input: ModelMutation = {
      kind: endpoint.is_active ? "retire" : "restore",
      endpoint,
    };
    try {
      const result = input.kind === "retire"
        ? await client.retireModelEndpoint(endpoint.id)
        : await client.restoreModelEndpoint(endpoint.id);
      if (finalizer.begin(
        input,
        result,
        input.kind === "retire" ? "Remove chat model" : "Restore chat model",
      )) {
        setMessage(`${input.kind === "retire" ? "Removal" : "Restore"} is waiting for approval in the originating chat.`);
        setPendingRemoval(null);
      } else if (result.status === "ok") {
        setMessage(input.kind === "retire"
          ? `${endpoint.model} was retired from model routing.`
          : `${endpoint.model} was restored to model routing.`);
        setPendingRemoval(null);
        await refresh(false);
      } else {
        setMessage(governedResultReason(result, `${endpoint.model} was not changed.`));
      }
    } catch {
      setMessage("Model lifecycle management is unavailable.");
    } finally {
      setBusy(false);
    }
  }

  async function prepareRemoval(endpoint: ModelEndpointInfo) {
    finalizer.invalidate();
    setBusy(true);
    setMessage("");
    try {
      const detail = await client.modelEndpoint(endpoint.id);
      if (!detail.endpoint.is_active) {
        setMessage("This model route is already retired.");
        return;
      }
      setPendingRemoval(detail.endpoint);
    } catch {
      setMessage("The route references could not be loaded, so the model was not removed.");
    } finally {
      setBusy(false);
    }
  }

  function toggleModality(modality: EndpointModality, checked: boolean) {
    finalizer.invalidate();
    setModalities((current) => {
      if (checked) return Array.from(new Set([...current, modality]));
      return current.length === 1 ? current : current.filter((item) => item !== modality);
    });
  }

  return (
    <div className="model-settings-pane">
      {head && <SectionHead section="models" />}
      <ModelSettingsTabs
        active={activeView}
        onChange={(view) => {
          finalizer.invalidate();
          clearForm(false, view);
          setActiveView(view);
        }}
      />
      <p className="model-settings-intro">
        Routes are tenant-owned and credential-free here. Provider keys stay in the kernel;
        agents may override a route without receiving the key itself.
      </p>
      <ModelRouteInventory
        activeView={activeView}
        choiceProjectionAvailable={choiceProjectionAvailable}
        choices={choices}
        endpoints={endpoints}
        inventoryAvailable={inventoryAvailable}
        loading={loading}
        mutationBusy={mutationBusy}
        onChange={(endpoint) => { void edit(endpoint); }}
        onLifecycle={(endpoint) => { void changeLifecycle(endpoint); }}
        onPrepareRemoval={(endpoint) => { void prepareRemoval(endpoint); }}
      />

      {pendingRemoval && (
        <ModelRemovalDialog
          busy={mutationBusy}
          endpoint={pendingRemoval}
          onCancel={() => setPendingRemoval(null)}
          onConfirm={() => { void changeLifecycle(pendingRemoval); }}
        />
      )}

      {activeView === "voice" && <VoiceAdapterInventory />}

      {activeView !== "voice" && (
        <BifrostCataloguePanel
          activeView={activeView}
          models={catalogueModels}
          reason={catalogueReason}
          status={catalogueStatus}
        />
      )}

      <ModelEditorForm
        activeView={activeView}
        busy={busy}
        catalogueModels={catalogueModels}
        catalogueStatus={catalogueStatus}
        endpointKind={endpointKind}
        hydratedExisting={hydratedExisting}
        hydratedReferences={hydratedReferences}
        id={id}
        inventoryAvailable={inventoryAvailable}
        loading={loading}
        modalities={modalities}
        model={model}
        mutationBusy={mutationBusy}
        onAddAnother={() => clearForm()}
        onIdChange={(value) => {
          finalizer.invalidate();
          setId(value);
        }}
        onModelChange={(value) => {
          finalizer.invalidate();
          setModel(value);
        }}
        onSubmit={(event) => { void save(event); }}
        onToggleModality={toggleModality}
      />

      {message && <p className="notice model-settings-notice" role="status">{message}</p>}
      <ExactApprovalFinalizer controller={finalizer} />
    </div>
  );
}
