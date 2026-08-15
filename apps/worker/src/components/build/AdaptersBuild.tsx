import { useEffect, useState } from "react";
import type {
  ActivateAdapterRequest,
  ActivateAdapterResponse,
  AdapterRecord,
  GovernedRouteResponse,
  StatusAck,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import {
  ExactApprovalFinalizer,
  governedResultReason,
  useExactApprovalFinalizer,
} from "../ExactApprovalFinalizer";
import { Unavailable } from "../Shell";
import { McpServersBuild } from "./McpServersBuild";

type AdapterLifecycleAction = "activate" | "deactivate" | "delete";

interface AdapterLifecycleMutation {
  action: AdapterLifecycleAction;
  adapterId: string;
  selectedAdapter: AdapterRecord | null;
  selectedAdapterId: string;
  source: string;
  body: ActivateAdapterRequest;
}

type AdapterLifecycleResult = GovernedRouteResponse<
  ActivateAdapterResponse | StatusAck
>;

function sameRecord(
  left: AdapterRecord | null,
  right: AdapterRecord | null,
): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

export function AdaptersBuild() {
  const [adapters, setAdapters] = useState<AdapterRecord[]>([]);
  const [adapterId, setAdapterId] = useState("");
  const [selectedInventoryAdapterId, setSelectedInventoryAdapterId] = useState("");
  const [spec, setSpec] = useState("{}");
  const [source, setSource] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [mcpId, setMcpId] = useState("");
  const [mcpUrl, setMcpUrl] = useState("");
  const [mcpCredentialRef, setMcpCredentialRef] = useState("");
  const [mcpCredentialId, setMcpCredentialId] = useState("");
  const [mcpCredentialStore, setMcpCredentialStore] = useState("env");
  const [mcpCredentialKind, setMcpCredentialKind] = useState("api_key");
  const [mcpAllowInternal, setMcpAllowInternal] = useState(false);
  const [mcpRefreshToken, setMcpRefreshToken] = useState(0);
  const [armed, setArmed] = useState("");
  const [message, setMessage] = useState("");
  const [lifecycleBusy, setLifecycleBusy] = useState(false);

  const selectedInventoryAdapter = adapters.find(
    (adapter) => adapter.id === selectedInventoryAdapterId,
  ) ?? null;
  const selectedInventoryAdapterIsMcp = selectedInventoryAdapter?.runtime === "mcp";
  const selectedInventoryAdapterIsActive =
    selectedInventoryAdapter?.activated === true;
  const selectedInventoryAdapterIsInert =
    selectedInventoryAdapter?.activated === false;

  async function mutateAdapterLifecycle(
    input: AdapterLifecycleMutation,
    approvalId?: string,
  ): Promise<AdapterLifecycleResult> {
    if (input.action === "activate") {
      return client.activateAdapter(input.adapterId, input.body, approvalId);
    }
    if (input.action === "deactivate") {
      return client.deactivateAdapter(input.adapterId, approvalId);
    }
    return client.deleteAdapter(input.adapterId, approvalId);
  }

  async function finishAdapterLifecycle(input: AdapterLifecycleMutation) {
    setArmed("");
    if (input.action === "delete") {
      setAdapterId("");
      setSelectedInventoryAdapterId("");
      setSource("");
    }
    setMessage(
      input.action === "activate"
        ? `Adapter ${input.adapterId} activated.`
        : input.action === "deactivate"
          ? `Adapter ${input.adapterId} deactivated.`
          : `Adapter ${input.adapterId} deleted.`,
    );
    await refresh(false);
  }

  const lifecycleFinalizer = useExactApprovalFinalizer<
    AdapterLifecycleMutation,
    AdapterLifecycleResult
  >({
    isCurrent: (input) => (
      adapterId.trim() === input.adapterId
      && selectedInventoryAdapterId === input.selectedAdapterId
      && source === input.source
      && sameRecord(selectedInventoryAdapter, input.selectedAdapter)
      && (
        input.action !== "activate"
        || reviewer.trim() === (input.body.reviewer ?? "")
      )
    ),
    replay: (input, approvalId) => mutateAdapterLifecycle(input, approvalId),
    onApplied: (_result, input) => finishAdapterLifecycle(input),
    onRefused: (result) => setMessage(governedResultReason(
      result,
      "The adapter lifecycle change was refused.",
    )),
    onUncertain: async () => {
      setArmed("");
      await refresh(false);
      setMessage(
        "Canonical adapter inventory was refreshed. No lifecycle change is inferred.",
      );
    },
  });

  async function refresh(invalidate = true) {
    if (invalidate) {
      lifecycleFinalizer.invalidate();
      setArmed("");
    }
    try {
      const result = await client.adapters();
      setAdapters(result.adapters);
    } catch {
      setMessage("Adapter inventory is unavailable.");
    }
  }
  useEffect(() => {
    void refresh(false);
  }, []);

  const lifecycleApprovalOpen = (
    lifecycleFinalizer.state === "waiting"
    || lifecycleFinalizer.state === "checking"
    || lifecycleFinalizer.state === "unavailable"
  );

  async function generate(event: React.FormEvent) {
    event.preventDefault();
    try {
      const parsed: unknown = JSON.parse(spec);
      const result = await client.generateAdapter({ adapter_id: adapterId.trim(), spec: parsed });
      setMessage(
        result.status === "ok"
          ? `Adapter ${result.id ?? adapterId.trim()} generated inert. Review it before activation.`
          : `Not generated: ${result.reason ?? result.status}.`,
      );
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The adapter was not generated.");
    }
  }

  function editAdapterId(value: string) {
    lifecycleFinalizer.invalidate();
    setAdapterId(value);
    setSelectedInventoryAdapterId("");
    setSource("");
    setArmed("");
  }

  async function inspect(id: string, inventoryAdapter?: AdapterRecord) {
    lifecycleFinalizer.invalidate();
    setAdapterId(id);
    setSelectedInventoryAdapterId(inventoryAdapter?.id ?? "");
    setArmed("");
    if (inventoryAdapter?.runtime === "mcp") {
      setSource("");
      return;
    }
    try {
      const result = await client.adapterSource(id);
      setSource(result.source ?? result.error ?? "No source returned.");
    } catch {
      setSource("Source inspection is unavailable for this identity.");
    }
  }

  async function activate() {
    const id = adapterId.trim();
    if (!id) return;
    const input: AdapterLifecycleMutation = {
      action: "activate",
      adapterId: id,
      selectedAdapter: selectedInventoryAdapter,
      selectedAdapterId: selectedInventoryAdapterId,
      source,
      body: { reviewer: reviewer.trim() || undefined },
    };
    lifecycleFinalizer.clear();
    setLifecycleBusy(true);
    setMessage("");
    try {
      const result = await mutateAdapterLifecycle(input);
      if (lifecycleFinalizer.begin(input, result, `Adapter ${id} activation`)) {
        setMessage(`Adapter ${id} activation is waiting for approval.`);
      } else if (result.status === "ok") {
        await finishAdapterLifecycle(input);
      } else {
        setMessage(governedResultReason(result, "The adapter was not activated."));
      }
    } catch {
      setMessage("The adapter was not activated. Review and authorisation are required.");
    } finally {
      setLifecycleBusy(false);
    }
  }

  async function deactivate() {
    if (!adapterId.trim()) return;
    const key = `deactivate:${adapterId.trim()}`;
    if (armed !== key) {
      lifecycleFinalizer.invalidate();
      setArmed(key);
      return;
    }
    const input: AdapterLifecycleMutation = {
      action: "deactivate",
      adapterId: adapterId.trim(),
      selectedAdapter: selectedInventoryAdapter,
      selectedAdapterId: selectedInventoryAdapterId,
      source,
      body: {},
    };
    lifecycleFinalizer.clear();
    setLifecycleBusy(true);
    setMessage("");
    try {
      const result = await mutateAdapterLifecycle(input);
      if (lifecycleFinalizer.begin(
        input,
        result,
        `Adapter ${input.adapterId} deactivation`,
      )) {
        setMessage(`Adapter ${input.adapterId} deactivation is waiting for approval.`);
      } else if (result.status === "ok") {
        await finishAdapterLifecycle(input);
      } else {
        setMessage(governedResultReason(result, "The adapter was not deactivated."));
      }
    } catch {
      setMessage("The adapter was not deactivated.");
    } finally {
      setLifecycleBusy(false);
    }
  }

  async function remove() {
    if (!adapterId.trim()) return;
    const key = `delete:${adapterId.trim()}`;
    if (armed !== key) {
      lifecycleFinalizer.invalidate();
      setArmed(key);
      return;
    }
    const input: AdapterLifecycleMutation = {
      action: "delete",
      adapterId: adapterId.trim(),
      selectedAdapter: selectedInventoryAdapter,
      selectedAdapterId: selectedInventoryAdapterId,
      source,
      body: {},
    };
    lifecycleFinalizer.clear();
    setLifecycleBusy(true);
    setMessage("");
    try {
      const result = await mutateAdapterLifecycle(input);
      if (lifecycleFinalizer.begin(
        input,
        result,
        `Adapter ${input.adapterId} deletion`,
      )) {
        setMessage(`Adapter ${input.adapterId} deletion is waiting for approval.`);
      } else if (result.status === "ok") {
        await finishAdapterLifecycle(input);
      } else {
        setMessage(governedResultReason(result, "The adapter was not deleted."));
      }
    } catch {
      setMessage("The adapter was not deleted. Live adapters must be deactivated first.");
    } finally {
      setLifecycleBusy(false);
    }
  }

  async function registerMcp(event: React.FormEvent) {
    event.preventDefault();
    try {
      const result = await client.registerMcpServer({
        id: mcpId.trim(),
        url: mcpUrl.trim(),
        allow_internal: mcpAllowInternal || undefined,
        credential_ref: mcpCredentialRef.trim() || undefined,
        credential_id: mcpCredentialId.trim() || undefined,
        credential_store: mcpCredentialRef.trim()
          ? mcpCredentialStore.trim() || "env"
          : undefined,
        credential_kind: mcpCredentialRef.trim()
          ? mcpCredentialKind.trim() || "api_key"
          : undefined,
      });
      setMessage(
        result.status === "ok"
          ? `MCP server ${mcpId.trim()} registered.`
          : `Not registered: ${result.reason ?? result.status}.`,
      );
      if (result.status === "ok") setMcpRefreshToken((value) => value + 1);
    } catch {
      setMessage("The MCP server was not registered. Check its URL, identifier, and secret-store reference.");
    }
  }

  return (
    <div className="build-layout">
      <section className="settings-card build-inventory">
        <div className="section-heading"><div><p className="eyebrow">Inventory</p><h2>Registered adapters</h2></div><button className="secondary-button" onClick={() => void refresh()}>Refresh</button></div>
        {adapters.length === 0 ? <Unavailable title="No adapters visible">Generated adapters appear here inert until they are reviewed and activated.</Unavailable> : (
          <div className="data-list compact-list" role="region" aria-label="Registered adapters" tabIndex={0}>{adapters.map((adapter) => (
            <button className="data-row" key={adapter.id} onClick={() => void inspect(adapter.id, adapter)}>
              <span className={`activity-dot ${adapter.health}`} />
              <span className="data-row-copy"><strong>{adapter.id}</strong><small>{adapter.runtime} · {adapter.source}</small></span>
              <span className="row-meta">{adapter.activated ? "active" : "inert"}</span>
            </button>
          ))}</div>
        )}
      </section>
      <div className="build-forms">
        {message && <p className="notice" role="status">{message}</p>}
        <ExactApprovalFinalizer controller={lifecycleFinalizer} />
        <form className="settings-card author-form" onSubmit={(event) => void generate(event)}>
          <p className="eyebrow">Generate</p><h2>Create an inert adapter</h2>
          <label><span>Adapter identifier</span><input className="field-control" required value={adapterId} onChange={(event) => editAdapterId(event.target.value)} /></label>
          <label><span>Adapter specification (JSON)</span><textarea className="field-control code-field" rows={8} value={spec} onChange={(event) => setSpec(event.target.value)} /></label>
          <button className="primary-button">Generate inert adapter</button>
        </form>
        <section className="settings-card author-form">
          <p className="eyebrow">Review and activation</p><h2>Inspect generated source</h2>
          {selectedInventoryAdapterIsMcp ? (
            <p className="notice">
              Use MCP operations below. External MCP source and lifecycle controls
              are intentionally unavailable in the generic adapter surface.
            </p>
          ) : (
            <>
              <label><span>Adapter identifier</span><input className="field-control" required value={adapterId} onChange={(event) => editAdapterId(event.target.value)} /></label>
              <div className="inline-actions">
                <button className="secondary-button" disabled={!adapterId.trim()} onClick={() => void inspect(adapterId.trim())}>Load source</button>
                <input className="field-control" aria-label="Reviewer identity" placeholder="Reviewer identity (optional)" value={reviewer} onChange={(event) => {
                  lifecycleFinalizer.invalidate();
                  setReviewer(event.target.value);
                }} />
                {!selectedInventoryAdapterIsActive && (
                  <button className="danger-button" disabled={!adapterId.trim() || !source || lifecycleBusy || lifecycleFinalizer.busy || lifecycleApprovalOpen} onClick={() => void activate()}>Request activation</button>
                )}
                {!selectedInventoryAdapterIsInert && (
                  <button className={armed === `deactivate:${adapterId.trim()}` ? "danger-button armed" : "danger-button"} disabled={!adapterId.trim() || lifecycleBusy || lifecycleFinalizer.busy || lifecycleApprovalOpen} onClick={() => void deactivate()}>{armed === `deactivate:${adapterId.trim()}` ? "Confirm deactivate" : "Deactivate"}</button>
                )}
                {!selectedInventoryAdapterIsActive && (
                  <button className={armed === `delete:${adapterId.trim()}` ? "danger-button armed" : "danger-button"} disabled={!adapterId.trim() || lifecycleBusy || lifecycleFinalizer.busy || lifecycleApprovalOpen} onClick={() => void remove()}>{armed === `delete:${adapterId.trim()}` ? "Confirm delete" : "Delete inert adapter"}</button>
                )}
              </div>
              <pre className="source-preview">{source || "Select an adapter to inspect its generated source before activation."}</pre>
            </>
          )}
        </section>
        <form className="settings-card author-form" onSubmit={(event) => void registerMcp(event)}>
          <p className="eyebrow">MCP</p><h2>Connect an MCP server</h2>
          <div className="author-grid">
            <label><span>Identifier</span><input className="field-control" required value={mcpId} onChange={(event) => setMcpId(event.target.value)} /></label>
            <label><span>URL</span><input className="field-control" type="url" required value={mcpUrl} onChange={(event) => setMcpUrl(event.target.value)} /></label>
            <label><span>Secret-store reference</span><input className="field-control" value={mcpCredentialRef} onChange={(event) => setMcpCredentialRef(event.target.value)} placeholder="BOLTRIG_MCP_TOKEN" /></label>
            <label><span>Credential ID (optional)</span><input className="field-control" value={mcpCredentialId} onChange={(event) => setMcpCredentialId(event.target.value)} /></label>
            <label><span>Secret store</span><input className="field-control" value={mcpCredentialStore} onChange={(event) => setMcpCredentialStore(event.target.value)} /></label>
            <label><span>Credential kind</span><input className="field-control" value={mcpCredentialKind} onChange={(event) => setMcpCredentialKind(event.target.value)} /></label>
          </div>
          <label className="check-label"><input type="checkbox" checked={mcpAllowInternal} onChange={(event) => setMcpAllowInternal(event.target.checked)} />Allow an operator-vetted internal address (reviewed again at activation)</label>
          <p className="muted small">Enter the name of a secret held by the configured credential store. Raw bearer tokens never pass through this form or the audit path.</p>
          <button className="primary-button">Register server</button>
        </form>
        <McpServersBuild refreshToken={mcpRefreshToken} />
      </div>
    </div>
  );
}
