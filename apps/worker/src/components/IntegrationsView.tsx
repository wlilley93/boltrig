import { useEffect, useMemo, useState } from "react";
import {
  WORKER_INTEGRATION_CATALOGUE,
  type GovernedRouteResponse,
  type IntegrationCatalogueEntry,
  type IntegrationConnection,
  type IntegrationManualSecretContract,
  type RuntimeAddon,
  type StatusAck,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import {
  type DesktopOAuthReturnReadiness,
  desktopOAuthReturnReadiness,
  listenDesktopOAuthReturns,
} from "../desktop";
import {
  ExactApprovalFinalizer,
  governedResultReason,
  useExactApprovalFinalizer,
} from "./ExactApprovalFinalizer";
import { Topbar } from "./Shell";

type ConnectionApiState = "loading" | "available" | "unavailable";
type AddonApiState = "loading" | "available" | "denied" | "unavailable";

interface IntegrationRevocation {
  connection: IntegrationConnection;
}

type IntegrationRevocationResult = GovernedRouteResponse<StatusAck>;

function sameConnection(
  left: IntegrationConnection | null,
  right: IntegrationConnection | null,
): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

export function IntegrationsView() {
  const [catalogue, setCatalogue] = useState<IntegrationCatalogueEntry[]>([
    ...WORKER_INTEGRATION_CATALOGUE,
  ]);
  const [connections, setConnections] = useState<IntegrationConnection[]>([]);
  const [apiState, setApiState] = useState<ConnectionApiState>("loading");
  const [addons, setAddons] = useState<RuntimeAddon[]>([]);
  const [addonApiState, setAddonApiState] = useState<AddonApiState>("loading");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [message, setMessage] = useState("");
  const [setupBusy, setSetupBusy] = useState(false);
  const [disconnectBusy, setDisconnectBusy] = useState(false);
  const [disconnectArmed, setDisconnectArmed] = useState(false);
  const [oauthReturn, setOAuthReturn] =
    useState<DesktopOAuthReturnReadiness | null>(null);

  const visible = useMemo(() => catalogue.filter((item) => (
    `${item.label} ${item.category}`.toLowerCase().includes(query.toLowerCase())
  )), [catalogue, query]);
  const selectedEntry = catalogue.find((item) => item.id === selectedId) ?? null;
  const selectedConnection = connections.find(
    (item) => item.integration_id === selectedId,
  ) ?? null;

  async function finishRevocation(input: IntegrationRevocation) {
    setDisconnectArmed(false);
    setSelectedId(null);
    setMessage(`${input.connection.label} disconnected.`);
    await refresh(false);
  }

  const revocationFinalizer = useExactApprovalFinalizer<
    IntegrationRevocation,
    IntegrationRevocationResult
  >({
    isCurrent: (input) => (
      disconnectArmed
      && selectedId === input.connection.integration_id
      && sameConnection(selectedConnection, input.connection)
    ),
    replay: (input, approvalId) => client.disconnectIntegration(
      input.connection.id,
      approvalId,
    ),
    isApplied: (result) => result.status === "revoked",
    onApplied: (_result, input) => finishRevocation(input),
    onRefused: (result) => setMessage(governedResultReason(
      result,
      "The connection revocation was refused.",
    )),
    onUncertain: async () => {
      setDisconnectArmed(false);
      await refresh(false);
      setMessage(
        "Canonical connection state was refreshed. No revocation is inferred.",
      );
    },
  });

  async function refresh(invalidate = true) {
    if (invalidate) {
      revocationFinalizer.invalidate();
      setDisconnectArmed(false);
    }
    setApiState("loading");
    try {
      const [catalogueResult, connectionResult] = await Promise.all([
        client.integrationCatalogue(),
        client.integrationConnections(),
      ]);
      const authoritative = new Map(
        catalogueResult.integrations.map((entry) => [entry.id, entry]),
      );
      setCatalogue([
        ...WORKER_INTEGRATION_CATALOGUE.map(
          (entry) => authoritative.get(entry.id) ?? entry,
        ),
        ...catalogueResult.integrations.filter(
          (entry) => !WORKER_INTEGRATION_CATALOGUE.some(
            (preview) => preview.id === entry.id,
          ),
        ),
      ]);
      setConnections(connectionResult.connections);
      setApiState("available");
    } catch {
      setCatalogue([...WORKER_INTEGRATION_CATALOGUE]);
      setConnections([]);
      setApiState("unavailable");
    }
  }

  async function refreshAddons() {
    setAddonApiState("loading");
    try {
      const result = await client.addons();
      setAddons(result.addons);
      setAddonApiState("available");
    } catch (error) {
      setAddons([]);
      const status = (
        typeof error === "object"
        && error !== null
        && "status" in error
        && typeof error.status === "number"
      ) ? error.status : null;
      setAddonApiState(status === 401 || status === 403 ? "denied" : "unavailable");
    }
  }

  useEffect(() => {
    void refresh(false);
    void refreshAddons();
  }, []);

  useEffect(() => {
    let active = true;
    let unlisten = () => {};
    void desktopOAuthReturnReadiness()
      .then((readiness) => {
        if (active) setOAuthReturn(readiness);
      })
      .catch(() => {
        if (active) {
          setOAuthReturn({
            runtime: "desktop",
            state: "unavailable",
            callback_uri: null,
            provider_exchange: "unavailable",
            reason: "deep_link_readiness_unavailable",
          });
        }
      });
    void listenDesktopOAuthReturns((event) => {
      if (!active) return;
      setMessage(
        event.status === "denied"
          ? "Provider authorization was denied. No connection is assumed."
          : "Authorization returned to Worker, but provider exchange is not configured. No connection is assumed.",
      );
    }).then((stop) => {
      if (active) unlisten = stop;
      else stop();
    });
    return () => {
      active = false;
      unlisten();
    };
  }, []);

  async function connect(entry: IntegrationCatalogueEntry) {
    setMessage("");
    if (apiState !== "available") {
      setMessage("Connection authority is not exposed by this deployment.");
      return;
    }
    if (!entry.available || !entry.setup_supported) {
      setMessage(entry.setup_supported
        ? `${entry.label} is unavailable (${entry.availability_reason ?? entry.certification}).`
        : `${entry.label} has no certified setup contract. No credential was requested.`);
      return;
    }
    if (entry.setup_contract?.kind === "manual_secret") {
      setMessage("Enter the provider-declared fields below. Secret values are write-only.");
      return;
    }
    if (!entry.auth.includes("oauth2")) {
      setMessage(entry.auth.includes("manual_secret")
        ? "This connector does not publish a structured secret-field schema yet. No credential was requested."
        : "This connector needs a governed pairing contract that is not available yet.");
      return;
    }
    try {
      const result = await client.startIntegrationOAuth(entry.id);
      if (!result.authorization_url) {
        setMessage("The connector did not return an authorization URL.");
        return;
      }
      if (oauthReturn?.runtime === "web") {
        setMessage(
          "This deployment has no reviewed web OAuth callback contract. No authorization page was opened.",
        );
        return;
      }
      if (oauthReturn?.state !== "ready") {
        setMessage(
          "Native OAuth return is unavailable in this Worker build. No authorization page was opened.",
        );
        return;
      }
      setMessage(
        "Native return is ready, but this provider has no reviewed launch and token-exchange contract. No authorization page was opened.",
      );
    } catch {
      setMessage("OAuth setup is unavailable. No credential was sent.");
    }
  }

  async function submitManualSecret(
    entry: IntegrationCatalogueEntry,
    label: string,
    fields: Record<string, string>,
  ): Promise<boolean> {
    revocationFinalizer.invalidate();
    setDisconnectArmed(false);
    setSetupBusy(true);
    setMessage("");
    try {
      const result = await client.submitIntegrationSecret(entry.id, {
        fields,
        ...(label.trim() ? { label: label.trim() } : {}),
      });
      setConnections((current) => [
        ...current.filter((item) => item.id !== result.connection.id),
        result.connection,
      ]);
      setMessage(`${entry.label} connected. The submitted secret cannot be retrieved.`);
      return true;
    } catch {
      setMessage("The credential was refused or could not be sealed. No connection is assumed.");
      return false;
    } finally {
      setSetupBusy(false);
    }
  }

  async function refreshHealth(connection: IntegrationConnection) {
    revocationFinalizer.invalidate();
    setDisconnectArmed(false);
    setMessage("");
    try {
      const result = await client.integrationConnectionHealth(connection.id);
      setConnections((current) => current.map((item) => (
        item.id === result.connection.id ? result.connection : item
      )));
      setMessage(`${connection.label} health is ${result.connection.health}.`);
    } catch {
      setMessage("Connection health could not be verified.");
    }
  }

  async function disconnect(connection: IntegrationConnection) {
    if (!disconnectArmed) {
      revocationFinalizer.invalidate();
      setDisconnectArmed(true);
      return;
    }
    const input: IntegrationRevocation = { connection };
    revocationFinalizer.clear();
    setDisconnectBusy(true);
    setMessage("");
    try {
      const result = await client.disconnectIntegration(connection.id);
      if (revocationFinalizer.begin(
        input,
        result,
        `${connection.label} disconnection`,
      )) {
        setMessage(`${connection.label} disconnection is waiting for approval.`);
      } else if (result.status === "revoked") {
        await finishRevocation(input);
      } else {
        setMessage(governedResultReason(
          result,
          "The connection could not be revoked.",
        ));
      }
    } catch {
      setMessage("The connection could not be revoked.");
    } finally {
      setDisconnectBusy(false);
    }
  }

  function selectIntegration(id: string) {
    revocationFinalizer.invalidate();
    setSelectedId(id);
    setDisconnectArmed(false);
  }

  function closeIntegration() {
    revocationFinalizer.invalidate();
    setSelectedId(null);
    setDisconnectArmed(false);
  }

  const revocationApprovalOpen = (
    revocationFinalizer.state === "waiting"
    || revocationFinalizer.state === "checking"
    || revocationFinalizer.state === "unavailable"
  );

  return (
    <div className="page">
      <Topbar
        title="Integrations"
        status={apiState === "available" ? `${connections.length} connected` : "Catalogue preview"}
      />
      <div className="page-content">
        <RuntimeAddons
          addons={addons}
          state={addonApiState}
        />
        <div className="page-intro">
          <div>
            <h2>Work across your tools</h2>
            <p>Boltrig owns connection state and credentials. Worker only starts governed setup and never reads a stored secret.</p>
          </div>
          <input className="search" aria-label="Search integrations" placeholder="Search tools…" value={query} onChange={(event) => setQuery(event.target.value)} />
        </div>
        {apiState === "unavailable" && (
          <p className="integration-state" role="status">
            Connection management is not enabled. These 40 reviewed entries are presentation metadata, not working or certified connectors.
          </p>
        )}
        {apiState === "loading" && <p className="integration-state" role="status">Checking the governed connection service…</p>}
        {message && <p className="notice integration-notice" role="status">{message}</p>}
        <ExactApprovalFinalizer controller={revocationFinalizer} />
        <div className={`integration-layout ${selectedEntry ? "detail-open" : ""}`}>
          <div className="catalogue-grid">
            {visible.map((item) => {
              const connection = connections.find((candidate) => candidate.integration_id === item.id);
              const canConnect = apiState === "available" && item.available === true && item.setup_supported === true;
              const action = connection ? "Manage" : canConnect ? "Connect" : "Details";
              return (
                <article className="integration-card" key={item.id}>
                  <div className="integration-logo">{initials(item.label)}</div>
                  <div className="integration-copy">
                    <h3>{item.label}</h3>
                    <p>{item.description}</p>
                    <span className={`certification ${connection ? connection.health : item.certification}`}>
                      {connection ? connection.health : item.certification}
                    </span>
                  </div>
                  <button
                    title={connectTitle(item, apiState, Boolean(connection))}
                    aria-label={`${action} ${item.label}`}
                    onClick={() => {
                      selectIntegration(item.id);
                      if (
                        !connection
                        && canConnect
                        && item.setup_contract?.kind !== "manual_secret"
                      ) void connect(item);
                    }}
                  >
                    {action}
                  </button>
                </article>
              );
            })}
          </div>
          {selectedEntry && (
            <aside className="integration-detail" aria-label={`${selectedEntry.label} connection`}>
              <button className="icon-button integration-close" aria-label="Close connection details" onClick={closeIntegration}>×</button>
              <div className="integration-logo large">{initials(selectedEntry.label)}</div>
              <p className="eyebrow">{selectedEntry.category.replace("_", " ")}</p>
              <h2>{selectedEntry.label}</h2>
              <p>{selectedEntry.description}</p>
              <dl className="integration-facts">
                <div><dt>Certification</dt><dd>{selectedEntry.certification}</dd></div>
                <div><dt>Availability</dt><dd>{selectedEntry.available ? "available" : selectedEntry.availability_reason ?? "unverified"}</dd></div>
                <div><dt>Setup contract</dt><dd>{selectedEntry.setup_supported ? "supported" : "not configured"}</dd></div>
                <div><dt>Transport</dt><dd>{selectedEntry.transport}</dd></div>
                <div><dt>Authentication</dt><dd>{selectedEntry.auth.join(", ")}</dd></div>
                <div><dt>Connection API</dt><dd>{apiState}</dd></div>
                <div>
                  <dt>OAuth return</dt>
                  <dd>{oauthReturnLabel(oauthReturn)}</dd>
                </div>
              </dl>
              {selectedConnection ? (
                <>
                  <section className="connection-summary">
                    <strong>{selectedConnection.label}</strong>
                    <span className={`certification ${selectedConnection.health}`}>{selectedConnection.health}</span>
                    <p>{selectedConnection.credential_ref_present ? "A write-only credential reference is present." : "No credential reference is present."}</p>
                    <small>{selectedConnection.accounts.length} accounts · {selectedConnection.enabled_tools.length} enabled tools</small>
                  </section>
                  {selectedConnection.enabled_tools.length > 0 && <div className="skill-list">{selectedConnection.enabled_tools.map((tool) => <span key={tool}>{tool}</span>)}</div>}
                  <button className="secondary-button" onClick={() => void refreshHealth(selectedConnection)}>Refresh health</button>
                  <button
                    className={disconnectArmed ? "danger-button armed" : "danger-button"}
                    disabled={disconnectBusy || revocationFinalizer.busy || revocationApprovalOpen}
                    onClick={() => void disconnect(selectedConnection)}
                  >
                    {disconnectArmed ? "Confirm disconnect" : "Disconnect"}
                  </button>
                </>
              ) : (
                selectedEntry.available
                && selectedEntry.setup_supported
                && selectedEntry.setup_contract?.kind === "manual_secret"
                  ? (
                    <ManualSecretSetup
                      contract={selectedEntry.setup_contract}
                      defaultLabel={selectedEntry.label}
                      busy={setupBusy}
                      onSubmit={(label, fields) => submitManualSecret(
                        selectedEntry,
                        label,
                        fields,
                      )}
                    />
                  )
                  : (
                    <p className="integration-guard">
                      {selectedEntry.available && selectedEntry.setup_supported
                        ? "No governed connection is active."
                        : "Credential setup stays disabled until this connector passes staging certification."}
                    </p>
                  )
              )}
            </aside>
          )}
        </div>
      </div>
    </div>
  );
}

function ManualSecretSetup({
  contract,
  defaultLabel,
  busy,
  onSubmit,
}: {
  contract: IntegrationManualSecretContract;
  defaultLabel: string;
  busy: boolean;
  onSubmit(label: string, fields: Record<string, string>): Promise<boolean>;
}) {
  const blank = () => Object.fromEntries(contract.fields.map((field) => [field.name, ""]));
  const [label, setLabel] = useState(defaultLabel);
  const [fields, setFields] = useState<Record<string, string>>(blank);

  useEffect(() => {
    setLabel(defaultLabel);
    setFields(blank());
  }, [contract.version, defaultLabel]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    const submitted = { ...fields };
    setFields(blank());
    await onSubmit(label, submitted);
    for (const name of Object.keys(submitted)) submitted[name] = "";
  }

  return (
    <form className="integration-setup-form" aria-label={`Connect ${defaultLabel}`} onSubmit={(event) => void submit(event)}>
      <p className="integration-guard">
        Contract <code>{contract.version}</code> accepts only the fields below.
        Secret values are sealed once and never shown again.
      </p>
      <label>
        <span>Connection label</span>
        <input
          className="field-control"
          value={label}
          maxLength={200}
          required
          disabled={busy}
          onChange={(event) => setLabel(event.target.value)}
        />
      </label>
      {contract.fields.map((field) => (
        <label key={field.name}>
          <span>{field.label}</span>
          <input
            className="field-control"
            type={field.secret ? "password" : "text"}
            autoComplete="off"
            value={fields[field.name] ?? ""}
            minLength={field.min_length}
            maxLength={field.max_length}
            required={field.required}
            disabled={busy}
            onChange={(event) => setFields((current) => ({
              ...current,
              [field.name]: event.target.value,
            }))}
          />
        </label>
      ))}
      <button className="primary-button" disabled={busy || !label.trim()}>
        {busy ? "Sealing…" : "Seal and connect"}
      </button>
    </form>
  );
}

function RuntimeAddons({
  addons,
  state,
}: {
  addons: RuntimeAddon[];
  state: AddonApiState;
}) {
  return (
    <section className="runtime-addons" aria-label="Runtime add-ons">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Installed extensions</p>
          <h2>Runtime add-ons</h2>
        </div>
        {state === "available" && <small>{addons.length} installed</small>}
      </div>
      {state === "loading" && (
        <p className="integration-state" role="status">
          Checking the kernel add-on inventory…
        </p>
      )}
      {state === "denied" && (
        <p className="integration-state" role="status">
          Add-on inventory denied. Your current session cannot read this scope.
        </p>
      )}
      {state === "unavailable" && (
        <p className="integration-state" role="status">
          Add-on inventory unavailable.
        </p>
      )}
      {state === "available" && addons.length === 0 && (
        <p className="integration-state canonical-empty" role="status">
          No runtime add-ons are installed in this build.
        </p>
      )}
      {state === "available" && addons.length > 0 && (
        <div className="runtime-addon-grid">
          {addons.map((addon) => (
            <article className="runtime-addon-card" key={addon.id}>
              <div className="runtime-addon-heading">
                <div>
                  <h3>{addon.id}</h3>
                  <small>Version {addon.version}</small>
                </div>
                <span className={`addon-runtime-state ${addon.runtime.status}`}>
                  {runtimeLabel(addon.runtime.status)}
                </span>
              </div>
              <p className="addon-activation">
                Installed / {addon.activation}
              </p>
              <p>{runtimeReason(addon)}</p>
              <div className="addon-contributions" aria-label={`${addon.id} contributions`}>
                {addon.contributions.harness && <span>Agent guidance</span>}
                {addon.contributions.adapter && <span>Adapter binding</span>}
                {addon.contributions.consequence_hint && <span>Risk mapping</span>}
                {!Object.values(addon.contributions).some(Boolean) && (
                  <span>No declared contributions</span>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function runtimeLabel(status: RuntimeAddon["runtime"]["status"]): string {
  if (status === "ready") return "Ready";
  if (status === "inactive") return "Inactive";
  return status;
}

function runtimeReason(addon: RuntimeAddon): string {
  if (addon.runtime.status === "inactive") {
    return "Installed in this build but inactive for this deployment.";
  }
  const reason = addon.runtime.reason;
  if (reason === "not_configured") return "A required deployment setting is not configured.";
  if (reason === "record_missing") return "A required adapter record is missing.";
  if (reason === "not_loaded") return "A required adapter is configured but not loaded.";
  if (reason === "health_degraded") return "Canonical cached health reports degraded service.";
  if (reason === "health_down") return "Canonical cached health reports the service down.";
  if (reason === "health_unverified") return "Canonical health evidence has not been verified.";
  if (reason === "component_missing") return "A required runtime component is missing.";
  if (reason === "credential_missing") return "A required credential reference is missing.";
  if (reason === "evidence_unavailable") return "Readiness evidence is currently unavailable.";
  if (addon.configuration.status === "not_required") {
    return "This add-on has no runtime configuration requirements.";
  }
  return "All declared runtime requirements are ready.";
}

function connectTitle(
  entry: IntegrationCatalogueEntry,
  state: ConnectionApiState,
  connected: boolean,
): string | undefined {
  if (connected) return "Inspect the governed connection";
  if (state !== "available") return "Connection service is not enabled";
  if (!entry.available) return `Unavailable: ${entry.availability_reason ?? entry.certification}`;
  if (!entry.setup_supported) return "No certified setup contract is configured";
  return undefined;
}

function initials(value: string) {
  return value.split(/\s+/).map((word) => word[0]).join("").slice(0, 2).toUpperCase();
}

function oauthReturnLabel(
  readiness: DesktopOAuthReturnReadiness | null,
): string {
  if (!readiness) return "checking";
  if (readiness.runtime === "web") return "browser callback unavailable";
  if (readiness.state !== "ready") return "native callback unavailable";
  return "native return ready · provider exchange unavailable";
}
