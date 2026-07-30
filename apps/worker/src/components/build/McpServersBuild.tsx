import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import type {
  ActivateAdapterResponse,
  DeleteMcpServerResponse,
  GovernedRouteResponse,
  McpCredentialMode,
  McpServerAction,
  McpServerDetailResponse,
  McpServerSummary,
  UpdateMcpServerRequest,
  UpdateMcpServerResponse,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import {
  ExactApprovalFinalizer,
  governedResultReason,
  useExactApprovalFinalizer,
} from "../ExactApprovalFinalizer";
import { Unavailable } from "../Shell";

const STALE_AFTER_MS = 24 * 60 * 60 * 1_000;

type McpLifecycleAction = Exclude<McpServerAction, "update" | "delete">;
type McpMutation =
  | {
      action: McpLifecycleAction;
      server: McpServerSummary;
    }
  | {
      action: "update";
      server: McpServerSummary;
      body: UpdateMcpServerRequest;
    }
  | {
      action: "delete";
      server: McpServerSummary;
    };
type McpMutationResult = GovernedRouteResponse<
  ActivateAdapterResponse | UpdateMcpServerResponse | DeleteMcpServerResponse
>;

const FAILURE_LABELS: Record<string, string> = {
  credential_unavailable: "Credential unavailable",
  egress_denied: "Egress denied",
  transport_unavailable: "Transport unavailable",
  protocol_invalid: "Protocol invalid",
  discovery_invalid: "Tool discovery invalid",
  unexpected_failure: "Unexpected probe failure",
};

function sameRecord(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function stale(timestamp: string | null): boolean {
  if (!timestamp) return false;
  const value = Date.parse(timestamp);
  return !Number.isFinite(value) || Date.now() - value > STALE_AFTER_MS;
}

function formatTimestamp(timestamp: string | null): string {
  if (!timestamp) return "Never";
  const value = new Date(timestamp);
  return Number.isNaN(value.getTime())
    ? "Recorded time unavailable"
    : value.toLocaleString();
}

function failureLabel(code: string | null): string {
  if (!code) return "Failure class unavailable";
  return FAILURE_LABELS[code] ?? "Unclassified probe failure";
}

function probeLabel(server: McpServerSummary): string {
  const probe = server.last_probe;
  if (!probe) return "never checked";
  const age = stale(probe.checked_at) ? "stale" : "recorded";
  return probe.outcome === "failed"
    ? `${age} failure · ${failureLabel(probe.failure_code)}`
    : `${age} success`;
}

function actionLabel(action: McpServerAction): string {
  if (action === "probe") return "Probe server";
  if (action === "activate") return "Request activation";
  if (action === "deactivate") return "Request deactivation";
  if (action === "retire") return "Retire server";
  if (action === "restore") return "Restore server";
  if (action === "update") return "Replace configuration";
  return "Delete server";
}

function isLifecycleAction(action: McpServerAction): action is McpLifecycleAction {
  return action !== "update" && action !== "delete";
}

function updateRequest(fields: {
  url: string;
  allowInternal: boolean;
  credentialMode: McpCredentialMode;
  credentialRef: string;
  credentialId: string;
  credentialStore: string;
  credentialKind: string;
}): UpdateMcpServerRequest {
  const common = {
    url: fields.url.trim(),
    allow_internal: fields.allowInternal,
  };
  if (fields.credentialMode !== "replace") {
    return { ...common, credential_mode: fields.credentialMode };
  }
  return {
    ...common,
    credential_mode: "replace",
    credential_ref: fields.credentialRef.trim(),
    ...(fields.credentialId.trim()
      ? { credential_id: fields.credentialId.trim() }
      : {}),
    ...(fields.credentialStore.trim()
      ? { credential_store: fields.credentialStore.trim() }
      : {}),
    ...(fields.credentialKind.trim()
      ? { credential_kind: fields.credentialKind.trim() }
      : {}),
  };
}

export function McpServersBuild({ refreshToken = 0 }: { refreshToken?: number }) {
  const [servers, setServers] = useState<McpServerSummary[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<McpServerDetailResponse | null>(null);
  const [message, setMessage] = useState("");
  const [unavailable, setUnavailable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [replacementUrl, setReplacementUrl] = useState("");
  const [allowInternal, setAllowInternal] = useState(false);
  const [credentialMode, setCredentialMode] = useState<McpCredentialMode>("preserve");
  const [credentialRef, setCredentialRef] = useState("");
  const [credentialId, setCredentialId] = useState("");
  const [credentialStore, setCredentialStore] = useState("");
  const [credentialKind, setCredentialKind] = useState("");
  const [deleteArmed, setDeleteArmed] = useState(false);

  const finalizer = useExactApprovalFinalizer<McpMutation, McpMutationResult>({
    isCurrent: (input) => {
      const sameServer = selectedId === input.server.id
      && detail !== null
      && sameRecord(detail.server, input.server);
      if (!sameServer) return false;
      if (input.action !== "update") return true;
      return editing && sameRecord(input.body, updateRequest({
        url: replacementUrl,
        allowInternal,
        credentialMode,
        credentialRef,
        credentialId,
        credentialStore,
        credentialKind,
      }));
    },
    replay: (input, approvalId) => mutate(input, approvalId),
    onApplied: async (_result, input) => {
      if (input.action === "delete") {
        setSelectedId("");
        setDetail(null);
        setEditing(false);
        setDeleteArmed(false);
        await refresh(false, "");
        setMessage(`${input.server.id}: server deleted.`);
        return;
      }
      if (input.action === "update") {
        setEditing(false);
        setDeleteArmed(false);
        await refresh(false, input.server.id);
        setMessage(
          `${input.server.id}: configuration replaced. Saved tool and probe evidence was invalidated; run Probe server before activation.`,
        );
        return;
      }
      await refresh(false, input.server.id);
      setMessage(`${input.server.id}: ${actionLabel(input.action)} completed.`);
    },
    onRefused: (result) => {
      setMessage(governedResultReason(
        result,
        "The approved MCP lifecycle change was refused.",
      ));
    },
    onUncertain: async () => {
      await refresh(false, selectedId);
      setMessage(
        "Canonical MCP state was refreshed; no lifecycle change or probe is inferred.",
      );
    },
  });

  async function loadDetail(serverId: string, invalidate = true) {
    if (invalidate) finalizer.invalidate();
    setEditing(false);
    setDeleteArmed(false);
    setSelectedId(serverId);
    setMessage("");
    try {
      const result = await client.mcpServer(serverId);
      setDetail(result);
      setUnavailable(false);
    } catch {
      setDetail(null);
      setMessage("MCP server detail is unavailable for this identity.");
    }
  }

  async function refresh(invalidate = true, detailId = selectedId) {
    if (invalidate) {
      finalizer.invalidate();
      setMessage("");
    }
    try {
      const result = await client.mcpServers();
      setServers(result.servers);
      setUnavailable(false);
      if (detailId) {
        if (result.servers.some((server) => server.id === detailId)) {
          await loadDetail(detailId, false);
        } else {
          setSelectedId("");
          setDetail(null);
        }
      }
    } catch {
      setServers([]);
      setDetail(null);
      setUnavailable(true);
    }
  }

  useEffect(() => {
    void refresh(false);
  }, [refreshToken]);

  async function mutate(
    input: McpMutation,
    approvalId?: string,
  ): Promise<McpMutationResult> {
    if (input.action === "update") {
      return client.updateMcpServer(input.server.id, input.body, approvalId);
    }
    if (input.action === "delete") {
      return client.deleteMcpServer(input.server.id, approvalId);
    }
    if (input.action === "probe") {
      return client.probeMcpServer(input.server.id, approvalId);
    }
    if (input.action === "activate") {
      return client.activateMcpServer(input.server.id, approvalId);
    }
    if (input.action === "deactivate") {
      return client.deactivateMcpServer(input.server.id, approvalId);
    }
    if (input.action === "retire") {
      return client.retireMcpServer(input.server.id, approvalId);
    }
    return client.restoreMcpServer(input.server.id, approvalId);
  }

  async function lifecycle(action: McpLifecycleAction) {
    if (!detail || !detail.server.available_actions.includes(action) || busy) return;
    const input: McpMutation = { action, server: detail.server };
    setBusy(true);
    setMessage("");
    try {
      const result = await mutate(input);
      if (finalizer.begin(input, result, `MCP ${action}`)) {
        setMessage(`${actionLabel(action)} is waiting for approval in Inbox.`);
      } else if (result.status === "ok") {
        await refresh(false, detail.server.id);
        setMessage(`${detail.server.id}: ${actionLabel(action)} completed.`);
      } else {
        setMessage(governedResultReason(
          result,
          `${actionLabel(action)} was not completed.`,
        ));
      }
    } catch {
      setMessage(`${actionLabel(action)} is unavailable.`);
    } finally {
      setBusy(false);
    }
  }

  function openEditor() {
    if (
      !detail
      || detail.server.state !== "inert"
      || !detail.server.available_actions.includes("update")
    ) return;
    finalizer.invalidate();
    setReplacementUrl("");
    setAllowInternal(detail.server.endpoint.internal_egress_allowed);
    setCredentialMode("preserve");
    setCredentialRef("");
    setCredentialId("");
    setCredentialStore("");
    setCredentialKind("");
    setDeleteArmed(false);
    setEditing(true);
    setMessage("");
  }

  function changeEditor(update: () => void) {
    finalizer.invalidate();
    update();
  }

  async function submitUpdate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      !detail
      || detail.server.state !== "inert"
      || !detail.server.available_actions.includes("update")
      || busy
    ) return;
    const body = updateRequest({
      url: replacementUrl,
      allowInternal,
      credentialMode,
      credentialRef,
      credentialId,
      credentialStore,
      credentialKind,
    });
    const input: McpMutation = { action: "update", server: detail.server, body };
    setBusy(true);
    setMessage("");
    try {
      const result = await mutate(input);
      if (finalizer.begin(input, result, "MCP configuration replacement")) {
        setMessage("Configuration replacement is waiting for approval in Inbox.");
      } else if (result.status === "ok") {
        setEditing(false);
        await refresh(false, detail.server.id);
        setMessage(
          `${detail.server.id}: configuration replaced. Saved tool and probe evidence was invalidated; run Probe server before activation.`,
        );
      } else {
        setMessage(governedResultReason(
          result,
          "Configuration replacement was not completed.",
        ));
      }
    } catch {
      setMessage("Configuration replacement is unavailable.");
    } finally {
      setBusy(false);
    }
  }

  async function requestDelete() {
    if (
      !detail
      || !detail.server.available_actions.includes("delete")
      || busy
    ) return;
    if (!deleteArmed) {
      finalizer.invalidate();
      setEditing(false);
      setDeleteArmed(true);
      setMessage(
        `Deletion is permanent. Select “Confirm delete server” to remove ${detail.server.id}.`,
      );
      return;
    }
    const input: McpMutation = { action: "delete", server: detail.server };
    setBusy(true);
    setMessage("");
    try {
      const result = await mutate(input);
      if (finalizer.begin(input, result, "MCP server deletion")) {
        setMessage("Server deletion is waiting for approval in Inbox.");
      } else if (result.status === "ok") {
        const deletedId = detail.server.id;
        setSelectedId("");
        setDetail(null);
        setDeleteArmed(false);
        await refresh(false, "");
        setMessage(`${deletedId}: server deleted.`);
      } else {
        setMessage(governedResultReason(result, "Server deletion was not completed."));
      }
    } catch {
      setMessage("Server deletion is unavailable.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="settings-card author-form">
      <div className="section-heading">
        <div><p className="eyebrow">MCP operations</p><h2>External servers and tools</h2></div>
        <button className="secondary-button" onClick={() => void refresh()}>
          Refresh stored state
        </button>
      </div>
      <p className="muted small">
        Reads show durable receipts and the last saved tool snapshot. Opening or
        refreshing this view never contacts an external server; only Probe does.
        Stored evidence older than 24 hours is marked stale.
      </p>
      {message && <p className="notice" role="status">{message}</p>}
      <ExactApprovalFinalizer controller={finalizer} />
      {unavailable ? (
        <Unavailable title="MCP operations unavailable">
          This identity cannot read the author-scoped MCP registry.
        </Unavailable>
      ) : servers.length === 0 ? (
        <Unavailable title="No MCP servers visible">
          Register a server above. It remains inert until activation is approved.
        </Unavailable>
      ) : (
        <div className="data-list compact-list" aria-label="External MCP servers">
          {servers.map((server) => (
            <button
              className="data-row"
              key={server.id}
              aria-pressed={selectedId === server.id}
              onClick={() => void loadDetail(server.id)}
            >
              <span className={`activity-dot ${
                server.state === "retired"
                  ? "paused"
                  : server.last_probe?.outcome === "failed"
                    ? "warn"
                    : server.last_probe?.outcome === "succeeded"
                      ? "ok"
                      : "paused"
              }`} />
              <span className="data-row-copy">
                <strong>{server.id}</strong>
                <small>{server.operability.status} · probe {probeLabel(server)}</small>
              </span>
              <span className="row-meta">{server.state}</span>
            </button>
          ))}
        </div>
      )}
      {detail && (
        <div className="source-preview" aria-label="MCP server detail">
          <div className="section-heading">
            <div>
              <p className="eyebrow">{detail.server.state}</p>
              <h3>{detail.server.id}</h3>
            </div>
            <div className="inline-actions">
              {detail.server.available_actions.filter(isLifecycleAction).map((action) => (
                <button
                  className={action === "retire" ? "danger-button" : "secondary-button"}
                  type="button"
                  key={action}
                  disabled={busy || finalizer.busy}
                  onClick={() => void lifecycle(action)}
                >
                  {actionLabel(action)}
                </button>
              ))}
              {detail.server.state === "inert"
                && detail.server.available_actions.includes("update") && (
                  <button
                    className="secondary-button"
                    type="button"
                    disabled={busy || finalizer.busy}
                    onClick={openEditor}
                  >
                    Replace configuration
                  </button>
                )}
              {detail.server.available_actions.includes("delete") && (
                <button
                  className="danger-button"
                  type="button"
                  disabled={busy || finalizer.busy}
                  onClick={() => void requestDelete()}
                >
                  {deleteArmed ? "Confirm delete server" : "Delete server"}
                </button>
              )}
            </div>
          </div>
          {editing && (
            <form className="author-form" onSubmit={(event) => void submitUpdate(event)}>
              <div className="section-heading">
                <div>
                  <p className="eyebrow">Inactive-only correction</p>
                  <h4>Replace the complete connection configuration</h4>
                </div>
              </div>
              <p className="notice">
                The visible origin cannot reconstruct a hidden endpoint path.
                Enter the complete replacement URL. No hidden credential reference
                is prefilled or exposed.
              </p>
              <div className="settings-grid">
                <label>
                  <span>Complete replacement URL</span>
                  <input
                    className="field-control"
                    type="url"
                    required
                    maxLength={2048}
                    autoComplete="off"
                    value={replacementUrl}
                    onChange={(event) => changeEditor(
                      () => setReplacementUrl(event.target.value),
                    )}
                  />
                </label>
                <label>
                  <span>Credential handling</span>
                  <select
                    className="field-control"
                    value={credentialMode}
                    onChange={(event) => changeEditor(
                      () => setCredentialMode(event.target.value as McpCredentialMode),
                    )}
                  >
                    <option value="preserve">Preserve current credential</option>
                    <option value="replace">Replace with a named credential</option>
                    <option value="remove">Remove credential</option>
                  </select>
                </label>
                <label>
                  <span>Internal destinations</span>
                  <span>
                    <input
                      type="checkbox"
                      checked={allowInternal}
                      onChange={(event) => changeEditor(
                        () => setAllowInternal(event.target.checked),
                      )}
                    />{" "}
                    Allow operator-vetted internal egress
                  </span>
                </label>
              </div>
              {credentialMode === "replace" && (
                <div className="settings-grid">
                  <label>
                    <span>Credential reference</span>
                    <input
                      className="field-control"
                      required
                      maxLength={1024}
                      autoComplete="off"
                      value={credentialRef}
                      onChange={(event) => changeEditor(
                        () => setCredentialRef(event.target.value),
                      )}
                    />
                    <small>
                      Enter a configured credential reference name, never a secret value.
                    </small>
                  </label>
                  <label>
                    <span>Credential id (optional)</span>
                    <input
                      className="field-control"
                      maxLength={200}
                      autoComplete="off"
                      value={credentialId}
                      onChange={(event) => changeEditor(
                        () => setCredentialId(event.target.value),
                      )}
                    />
                  </label>
                  <label>
                    <span>Credential store (optional)</span>
                    <input
                      className="field-control"
                      maxLength={100}
                      autoComplete="off"
                      value={credentialStore}
                      onChange={(event) => changeEditor(
                        () => setCredentialStore(event.target.value),
                      )}
                    />
                  </label>
                  <label>
                    <span>Credential kind (optional)</span>
                    <input
                      className="field-control"
                      maxLength={100}
                      autoComplete="off"
                      value={credentialKind}
                      onChange={(event) => changeEditor(
                        () => setCredentialKind(event.target.value),
                      )}
                    />
                  </label>
                </div>
              )}
              <p className="muted small">
                A successful replacement increments the configuration revision,
                clears the saved tool snapshot plus all prior probe history and
                health authority, and leaves the server inert. Run Probe server
                again before activation.
              </p>
              <div className="inline-actions">
                <button
                  className="primary-button"
                  type="submit"
                  disabled={busy || finalizer.busy}
                >
                  Request configuration replacement
                </button>
                <button
                  className="secondary-button"
                  type="button"
                  disabled={busy || finalizer.busy}
                  onClick={() => {
                    finalizer.invalidate();
                    setEditing(false);
                  }}
                >
                  Cancel
                </button>
              </div>
            </form>
          )}
          {detail.server.state === "retired" && (
            <p className="notice">
              Retired servers are unavailable for execution. Their last probe
              evidence and saved tool snapshot remain historical, not live.
            </p>
          )}
          <dl>
            <div><dt>Endpoint</dt><dd>{detail.server.endpoint.origin ?? "Not configured"}{detail.server.endpoint.path_redacted ? " · path hidden" : ""}</dd></div>
            <div><dt>Configuration revision</dt><dd>{detail.server.config_revision}</dd></div>
            <div>
              <dt>Last explicit probe</dt>
              <dd>
                {!detail.server.last_probe
                  ? "Never checked"
                  : `${detail.server.last_probe.outcome === "failed"
                    ? failureLabel(detail.server.last_probe.failure_code)
                    : "Succeeded"} · ${formatTimestamp(detail.server.last_probe.checked_at)}${stale(detail.server.last_probe.checked_at) ? " · stale" : ""}`}
              </dd>
            </div>
            <div><dt>Runtime</dt><dd>{detail.server.runtime_loaded ? "loaded" : "unavailable"}</dd></div>
            <div><dt>Credential</dt><dd>{detail.server.credential_configured ? "reference configured" : "not configured"}</dd></div>
            <div><dt>Internal egress</dt><dd>{detail.server.endpoint.internal_egress_allowed ? "operator-vetted allowance" : "blocked"}</dd></div>
          </dl>
          <div className="section-heading">
            <div>
              <p className="eyebrow">Durable snapshot</p>
              <h4>Last-known tools</h4>
            </div>
            <span className="row-meta">
              {detail.server.tool_snapshot.observed_at
                ? `${formatTimestamp(detail.server.tool_snapshot.observed_at)}${stale(detail.server.tool_snapshot.observed_at) ? " · stale" : ""}`
                : "never discovered"}
              {" · "}{detail.server.tool_snapshot.publication_status.replaceAll("_", " ")}
            </span>
          </div>
          {detail.server.tool_snapshot.publication_status === "drifted" && (
            <p className="notice">
              The saved catalogue differs from currently published authority.
              Probe did not hot-publish it; deactivate and reactivate this server
              to apply the saved snapshot.
            </p>
          )}
          {detail.server.tool_snapshot.status === "never_discovered" ? (
            <p className="muted">
              No successful discovery snapshot has been stored. A successful
              explicit Probe may create one; this read did not contact the server.
            </p>
          ) : detail.tools.length === 0 ? (
            <p className="muted">
              The last saved discovery snapshot contains no tools.
            </p>
          ) : (
            <div className="data-list compact-list">
              {detail.tools.map((tool) => (
                <div className="data-row static" key={tool.id}>
                  <span className={`activity-dot ${tool.consequence === "high" ? "paused" : "ok"}`} />
                  <span className="data-row-copy"><strong>{tool.name}</strong><small>{tool.description || tool.id}</small></span>
                  <span className="row-meta">{tool.consequence}</span>
                </div>
              ))}
              {detail.tools_truncated && (
                <p className="muted">
                  Additional tools are not shown in this bounded snapshot.
                </p>
              )}
            </div>
          )}
          <div className="section-heading">
            <div>
              <p className="eyebrow">Bounded receipts</p>
              <h4>Probe history</h4>
            </div>
            <span className="row-meta">{detail.probe_history.length} shown</span>
          </div>
          {detail.probe_history.length === 0 ? (
            <p className="muted">
              This server has never stored an explicit probe receipt.
            </p>
          ) : (
            <div className="data-list compact-list" aria-label="MCP probe history">
              {detail.probe_history.slice(0, 10).map((probe) => (
                <div className="data-row static" key={probe.probe_id}>
                  <span className={`activity-dot ${probe.outcome === "succeeded" ? "ok" : "warn"}`} />
                  <span className="data-row-copy">
                    <strong>
                      {probe.outcome === "succeeded"
                        ? "Probe succeeded"
                        : failureLabel(probe.failure_code)}
                    </strong>
                    <small>
                      {formatTimestamp(probe.checked_at)} · {probe.tool_count} tool{probe.tool_count === 1 ? "" : "s"}
                    </small>
                  </span>
                  <span className="row-meta">
                    {stale(probe.checked_at) ? "stale receipt" : "recorded receipt"}
                  </span>
                </div>
              ))}
              {(detail.probe_history_truncated || detail.probe_history.length > 10) && (
                <p className="muted">
                  Additional historical probe receipts are not shown in this bounded view.
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
