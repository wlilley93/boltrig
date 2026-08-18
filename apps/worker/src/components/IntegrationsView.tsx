import { useEffect, useMemo, useRef, useState } from "react";
import {
  BoltrigApiError,
  WORKER_INTEGRATION_CATALOGUE,
  type GovernedRouteResponse,
  type IntegrationAuthKind,
  type IntegrationCatalogueEntry,
  type IntegrationConnection,
  type IntegrationSecretSubmission,
  type IntegrationManualSecretContract,
  type McpServerSummary,
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
import { ManualSecretSetup } from "./integrations/ManualSecretSetup";
import {
  AddPluginModal,
  PluginInventoryStatus,
  PluginPageHeading,
} from "./integrations/PluginPicker";
import "./IntegrationsView.css";

type ConnectionApiState = "loading" | "available" | "unavailable";
type InventoryApiState = "loading" | "available" | "denied" | "unavailable";
type InventoryStatusFilter = "all" | "connected" | "not-connected";
type IntegrationCategory = IntegrationCatalogueEntry["category"];
type InventoryCategory = IntegrationCategory | "mcp";
type HealthTone = "green" | "amber" | "red" | "unknown";

interface IntegrationRevocation {
  connection: IntegrationConnection;
}

type IntegrationRevocationResult = GovernedRouteResponse<StatusAck>;

interface HealthPresentation {
  label: string;
  tone: HealthTone;
}

interface InventoryGroupDefinition {
  id: InventoryCategory;
  label: string;
}

type InventoryItem =
  | {
    kind: "integration";
    key: string;
    category: IntegrationCategory;
    label: string;
    connected: boolean;
    entry: IntegrationCatalogueEntry;
    connection: IntegrationConnection | null;
  }
  | {
    kind: "mcp";
    key: string;
    category: "mcp";
    label: string;
    connected: boolean;
    server: McpServerSummary;
  };

interface PluginIssue {
  key: string;
  summary: string;
}

const GROUPS: readonly InventoryGroupDefinition[] = [
  { id: "crm_sales", label: "Customer records" },
  { id: "communications", label: "Conversation" },
  { id: "work", label: "Work tracking" },
  { id: "analytics_operations", label: "Operations and analytics" },
  { id: "finance", label: "Money" },
  { id: "storage_design", label: "Files and design" },
  { id: "browser", label: "Browser and web" },
  { id: "mcp", label: "Your own servers" },
];

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
  const [mcpServers, setMcpServers] = useState<McpServerSummary[]>([]);
  const [mcpApiState, setMcpApiState] = useState<InventoryApiState>("loading");
  const [mcpTruncated, setMcpTruncated] = useState(false);
  const [addons, setAddons] = useState<RuntimeAddon[]>([]);
  const [addonApiState, setAddonApiState] = useState<InventoryApiState>("loading");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [reviewIssueKeys, setReviewIssueKeys] = useState<string[]>([]);
  const [issueFocusKey, setIssueFocusKey] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<InventoryStatusFilter>("all");
  const [categoryFilter, setCategoryFilter] = useState<InventoryCategory | null>(null);
  const [filterOpen, setFilterOpen] = useState(false);
  const [addPluginOpen, setAddPluginOpen] = useState(false);
  const [setupEntryId, setSetupEntryId] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [setupBusy, setSetupBusy] = useState(false);
  const [healthBusyId, setHealthBusyId] = useState<string | null>(null);
  const [disconnectBusy, setDisconnectBusy] = useState(false);
  const [disconnectArmed, setDisconnectArmed] = useState(false);
  const [oauthReturn, setOAuthReturn] =
    useState<DesktopOAuthReturnReadiness | null>(null);
  const inventoryRef = useRef<HTMLDivElement>(null);

  const selectedId = selectedKey?.startsWith("integration:")
    ? selectedKey.slice("integration:".length)
    : null;
  const selectedConnection = connections.find(
    (item) => item.integration_id === selectedId,
  ) ?? null;
  const connectionsByIntegration = useMemo(
    () => new Map(connections.map((item) => [item.integration_id, item])),
    [connections],
  );

  const inventory = useMemo<InventoryItem[]>(() => [
    ...catalogue.map((entry): InventoryItem => {
      const connection = connectionsByIntegration.get(entry.id) ?? null;
      return {
        kind: "integration",
        key: integrationKey(entry.id),
        category: entry.category,
        label: entry.label,
        connected: Boolean(connection && connection.health !== "revoked"),
        entry,
        connection,
      };
    }),
    ...mcpServers.map((server): InventoryItem => ({
      kind: "mcp",
      key: mcpKey(server.id),
      category: "mcp",
      label: server.id,
      connected: server.state !== "retired",
      server,
    })),
  ], [catalogue, connectionsByIntegration, mcpServers]);

  const groups = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    const matching = inventory.filter((item) => {
      if (reviewIssueKeys.length > 0 && !reviewIssueKeys.includes(item.key)) return false;
      if (statusFilter === "connected" && !item.connected) return false;
      if (statusFilter === "not-connected" && item.connected) return false;
      if (categoryFilter && item.category !== categoryFilter) return false;
      if (!normalizedQuery) return true;
      return inventorySearchText(item).includes(normalizedQuery);
    });

    return GROUPS.map((group) => ({
      ...group,
      items: matching
        .filter((item) => item.category === group.id)
        .sort((left, right) => (
          Number(right.connected) - Number(left.connected)
          || left.label.localeCompare(right.label)
        )),
    })).filter((group) => group.items.length > 0);
  }, [categoryFilter, inventory, query, reviewIssueKeys, statusFilter]);

  const categoryCounts = useMemo(() => {
    const matchingStatus = inventory.filter((item) => (
      statusFilter === "all"
      || (statusFilter === "connected" ? item.connected : !item.connected)
    ));
    return new Map<InventoryCategory | null, number>([
      [null, matchingStatus.length],
      ...GROUPS.map((group): [InventoryCategory, number] => [
        group.id,
        matchingStatus.filter((item) => item.category === group.id).length,
      ]),
    ]);
  }, [inventory, statusFilter]);

  const connectedCount = inventory.filter((item) => item.connected).length;
  const activeFilterCount = (
    (statusFilter === "all" ? 0 : 1)
    + (categoryFilter ? 1 : 0)
    + (reviewIssueKeys.length > 0 ? 1 : 0)
  );
  const issues = useMemo<PluginIssue[]>(() => [
    ...connections.flatMap((connection) => {
      if (connection.health !== "degraded" && connection.health !== "down") return [];
      const label = catalogue.find((entry) => entry.id === connection.integration_id)?.label
        ?? connection.label;
      return [{
        key: integrationKey(connection.integration_id),
        summary: `${label} is ${connection.health}`,
      }];
    }),
    ...mcpServers.flatMap((server) => {
      const summary = mcpIssueSummary(server);
      return summary ? [{ key: mcpKey(server.id), summary }] : [];
    }),
  ], [catalogue, connections, mcpServers]);

  useEffect(() => {
    const currentKeys = new Set(issues.map((issue) => issue.key));
    setReviewIssueKeys((current) => current.filter((key) => currentKeys.has(key)));
  }, [issues]);

  useEffect(() => {
    if (!issueFocusKey) return;
    const row = Array.from(
      inventoryRef.current?.querySelectorAll<HTMLElement>("[data-plugin-key]") ?? [],
    ).find((candidate) => candidate.dataset.pluginKey === issueFocusKey);
    const toggle = row?.querySelector<HTMLButtonElement>(".plugins-row-toggle");
    if (!row || !toggle) return;
    row.scrollIntoView?.({ block: "center" });
    toggle.focus({ preventScroll: true });
    setIssueFocusKey(null);
  }, [groups, issueFocusKey]);

  async function finishRevocation(input: IntegrationRevocation) {
    setDisconnectArmed(false);
    setSelectedKey(null);
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

  async function refreshMcpServers() {
    setMcpApiState("loading");
    try {
      const result = await client.mcpServers();
      setMcpServers(result.servers);
      setMcpTruncated(result.truncated);
      setMcpApiState("available");
    } catch (error) {
      setMcpServers([]);
      setMcpTruncated(false);
      const status = errorStatus(error);
      setMcpApiState(status === 401 || status === 403 ? "denied" : "unavailable");
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
      const status = errorStatus(error);
      setAddonApiState(status === 401 || status === 403 ? "denied" : "unavailable");
    }
  }

  useEffect(() => {
    void refresh(false);
    void refreshMcpServers();
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
        : `${entry.label} has no reviewed setup contract. No credential was requested.`);
      return;
    }
    if (entry.setup_contract?.kind === "manual_secret") {
      setSetupEntryId(entry.id);
      setMessage("Enter only the provider-declared fields below. Secret values are write-only.");
      return;
    }
    if (!entry.auth.includes("oauth2")) {
      setMessage(entry.auth.includes("manual_secret")
        ? "This connector does not publish a structured secret-field schema. No credential was requested."
        : "This connector needs a pairing method that is not available here.");
      return;
    }
    setSetupEntryId(null);
    try {
      const result = await client.startIntegrationOAuth(entry.id);
      if (!result.authorization_url) {
        setMessage("The connector did not return an authorization URL. No connection is assumed.");
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
    } catch (error) {
      const reason = errorReason(error);
      if (errorStatus(error) === 409 && reason === "oauth_provider_not_configured") {
        setMessage(
          `${entry.label} declares OAuth, but this deployment has no configured provider launch. No authorization page was opened and no connection is assumed.`,
        );
      } else if (errorStatus(error) === 409 && reason === "oauth_not_declared") {
        setMessage(
          `${entry.label} does not declare OAuth in the authoritative catalogue. No credential was sent.`,
        );
      } else {
        setMessage("OAuth setup is unavailable. No credential was sent and no connection is assumed.");
      }
    }
  }

  async function submitManualSecret(
    entry: IntegrationCatalogueEntry,
    submission: IntegrationSecretSubmission,
  ): Promise<boolean> {
    revocationFinalizer.invalidate();
    setDisconnectArmed(false);
    setSetupBusy(true);
    setMessage("");
    try {
      const result = await client.submitIntegrationSecret(entry.id, submission);
      setConnections((current) => [
        ...current.filter((item) => item.id !== result.connection.id),
        result.connection,
      ]);
      setSetupEntryId(null);
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
    setHealthBusyId(connection.id);
    setMessage("");
    try {
      const result = await client.integrationConnectionHealth(connection.id);
      setConnections((current) => current.map((item) => (
        item.id === result.connection.id ? result.connection : item
      )));
      setMessage(
        `${connection.label} health is ${integrationHealthPresentation(result.connection.health).label.toLowerCase()}.`,
      );
    } catch {
      setMessage("Connection health could not be verified. The previous state is unchanged.");
    } finally {
      setHealthBusyId(null);
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

  function toggleIntegration(id: string) {
    revocationFinalizer.invalidate();
    setDisconnectArmed(false);
    setSetupEntryId(null);
    const key = integrationKey(id);
    setSelectedKey((current) => current === key ? null : key);
  }

  function toggleMcpServer(id: string) {
    revocationFinalizer.invalidate();
    setDisconnectArmed(false);
    setSetupEntryId(null);
    const key = mcpKey(id);
    setSelectedKey((current) => current === key ? null : key);
  }

  function closeSelected() {
    revocationFinalizer.invalidate();
    setDisconnectArmed(false);
    setSetupEntryId(null);
    setReviewIssueKeys([]);
    setSelectedKey(null);
  }

  function focusIssues() {
    const first = issues[0];
    if (!first) return;
    revocationFinalizer.invalidate();
    setQuery("");
    setStatusFilter("all");
    setCategoryFilter(null);
    setFilterOpen(false);
    setSelectedKey(first.key);
    setReviewIssueKeys(issues.map((issue) => issue.key));
    setIssueFocusKey(first.key);
  }

  function clearFilters() {
    revocationFinalizer.invalidate();
    setQuery("");
    setStatusFilter("all");
    setCategoryFilter(null);
    setReviewIssueKeys([]);
    setSelectedKey(null);
    setSetupEntryId(null);
    setDisconnectArmed(false);
  }

  function changeQuery(value: string) {
    revocationFinalizer.invalidate();
    setDisconnectArmed(false);
    setSetupEntryId(null);
    setReviewIssueKeys([]);
    setSelectedKey(null);
    setQuery(value);
  }

  function changeStatusFilter(value: InventoryStatusFilter) {
    revocationFinalizer.invalidate();
    setDisconnectArmed(false);
    setSetupEntryId(null);
    setReviewIssueKeys([]);
    setSelectedKey(null);
    setStatusFilter(value);
  }

  function changeCategoryFilter(value: InventoryCategory | null) {
    revocationFinalizer.invalidate();
    setDisconnectArmed(false);
    setSetupEntryId(null);
    setReviewIssueKeys([]);
    setSelectedKey(null);
    setCategoryFilter(value);
  }

  function choosePlugin(entry: IntegrationCatalogueEntry) {
    clearFilters();
    const key = integrationKey(entry.id);
    setSelectedKey(key);
    setSetupEntryId(canStartIntegrationSetup(entry, apiState) ? entry.id : null);
    setIssueFocusKey(key);
    setAddPluginOpen(false);
  }

  const revocationApprovalOpen = (
    revocationFinalizer.state === "waiting"
    || revocationFinalizer.state === "checking"
    || revocationFinalizer.state === "unavailable"
  );

  return (
    <div className="plugins-page">
      <main className="plugins-pane">
        <PluginPageHeading onAdd={() => setAddPluginOpen(true)} />

        <div className="plugins-wrap">
          {issues.length > 0 && (
            <aside className="plugins-alert" aria-label="Connection health issues">
              <span className="plugins-alert-dot" aria-hidden />
              <span className="plugins-alert-copy">
                <strong>{issues.length === 1
                  ? "One needs you"
                  : issues.length === 2
                    ? "Two need you"
                    : `${issues.length} need you`}</strong>
                <span>{joinIssueSummaries(issues.map((issue) => issue.summary))}.</span>
              </span>
              <button onClick={focusIssues} type="button">
                {issues.length === 2 ? "Look at both" : "Look at it"}
              </button>
            </aside>
          )}

          <section className="plugins-inventory" aria-labelledby="plugins-connections-heading">
            <div className="plugins-inventory-heading">
              <h2 id="plugins-connections-heading">Connections</h2>
              <span>{connectedCount} connected of {inventory.length}</span>
            </div>

            <div className="plugins-toolbar">
              <label className="plugins-search">
                <SearchIcon />
                <span className="sr-only">Search integrations</span>
                <input
                  aria-label="Search integrations"
                  onChange={(event) => changeQuery(event.target.value)}
                  placeholder="Search connections…"
                  value={query}
                />
                {query.trim() && (
                  <button aria-label="Clear connection search" onClick={() => changeQuery("")} type="button">
                    Clear
                  </button>
                )}
              </label>

              <div className="plugins-filter-wrap">
                <button
                  aria-expanded={filterOpen}
                  className={`plugins-filter-button ${filterOpen || activeFilterCount ? "active" : ""}`}
                  onClick={() => setFilterOpen((current) => !current)}
                  type="button"
                >
                  <FilterIcon />
                  <span>Filters</span>
                  {activeFilterCount > 0 && <span className="plugins-filter-count">{activeFilterCount}</span>}
                </button>

                {filterOpen && (
                  <div className="plugins-filter-popover" role="dialog" aria-label="Connection filters">
                    <div className="plugins-filter-section">
                      <span className="plugins-filter-label">Status</span>
                      <div className="plugins-segments">
                        {([
                          ["all", "All"],
                          ["connected", "Connected"],
                          ["not-connected", "Not yet"],
                        ] as const).map(([value, label]) => (
                          <button
                            aria-pressed={statusFilter === value}
                            className={statusFilter === value ? "active" : ""}
                            key={value}
                            onClick={() => changeStatusFilter(value)}
                            type="button"
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                    </div>

                    <div className="plugins-category-heading">Category</div>
                    <div className="plugins-category-list">
                      <CategoryFilterRow
                        active={categoryFilter === null}
                        count={categoryCounts.get(null) ?? 0}
                        label="All categories"
                        onClick={() => changeCategoryFilter(null)}
                      />
                      {GROUPS.filter((group) => (
                        (categoryCounts.get(group.id) ?? 0) > 0
                        || categoryFilter === group.id
                      )).map((group) => (
                        <CategoryFilterRow
                          active={categoryFilter === group.id}
                          count={categoryCounts.get(group.id) ?? 0}
                          key={group.id}
                          label={group.label}
                          onClick={() => changeCategoryFilter(group.id)}
                        />
                      ))}
                    </div>

                    <div className="plugins-filter-footer">
                      <button
                        className="plugins-clear-filters"
                        disabled={!activeFilterCount && !query.trim()}
                        onClick={clearFilters}
                        type="button"
                      >
                        Clear all
                      </button>
                      <button className="plugins-filter-done" onClick={() => setFilterOpen(false)} type="button">
                        Done
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>

            <PluginInventoryStatus
              connectionState={apiState}
              mcpState={mcpApiState}
              mcpTruncated={mcpTruncated}
            />
            {message && <p className="plugins-notice" role="status">{message}</p>}
            <ExactApprovalFinalizer controller={revocationFinalizer} />

            <div className="plugins-groups" ref={inventoryRef}>
              {groups.map((group) => (
                <section className="plugins-group" key={group.id} aria-labelledby={`plugins-group-${group.id}`}>
                  <header>
                    <h3 id={`plugins-group-${group.id}`}>{group.label}</h3>
                    <span>
                      {group.items.length} {group.id === "mcp"
                        ? group.items.length === 1 ? "server" : "servers"
                        : group.items.length === 1 ? "service" : "services"}
                    </span>
                  </header>
                  <div>
                    {group.items.map((item) => item.kind === "integration" ? (
                      <IntegrationRow
                        apiState={apiState}
                        connection={item.connection}
                        disconnectArmed={disconnectArmed}
                        disconnectBusy={disconnectBusy}
                        entry={item.entry}
                        healthBusy={healthBusyId === item.connection?.id}
                        inventoryKey={item.key}
                        key={item.key}
                        oauthReturn={oauthReturn}
                        onClose={closeSelected}
                        onConnect={() => void connect(item.entry)}
                        onDisconnect={(connection) => void disconnect(connection)}
                        onHealth={(connection) => void refreshHealth(connection)}
                        onSubmit={(s) => submitManualSecret(item.entry, s)}
                        onToggle={() => toggleIntegration(item.entry.id)}
                        open={selectedKey === item.key}
                        revocationBusy={revocationFinalizer.busy || revocationApprovalOpen}
                        setupBusy={setupBusy}
                        setupOpen={setupEntryId === item.entry.id}
                      />
                    ) : (
                      <McpRow
                        inventoryKey={item.key}
                        key={item.key}
                        onToggle={() => toggleMcpServer(item.server.id)}
                        open={selectedKey === item.key}
                        server={item.server}
                      />
                    ))}
                  </div>
                </section>
              ))}
              {groups.length === 0 && (
                <p className="plugins-empty" role="status">
                  Nothing here matches. Clear the filters to see the inventory reported by this deployment.
                </p>
              )}
            </div>
          </section>
        </div>

        <details className="plugins-system-details">
          <summary>
            <span>System details</span>
            <small>Installed extensions and deployment status</small>
          </summary>
          <RuntimeAddons addons={addons} state={addonApiState} />
        </details>
      </main>
      {addPluginOpen && (
        <AddPluginModal
          connectedIds={new Set(connections.map((item) => item.integration_id))}
          entries={catalogue}
          onClose={() => setAddPluginOpen(false)}
          onSelect={choosePlugin}
        />
      )}
    </div>
  );
}

function IntegrationRow({
  apiState,
  connection,
  disconnectArmed,
  disconnectBusy,
  entry,
  healthBusy,
  inventoryKey,
  oauthReturn,
  onClose,
  onConnect,
  onDisconnect,
  onHealth,
  onSubmit,
  onToggle,
  open,
  revocationBusy,
  setupBusy,
  setupOpen,
}: {
  apiState: ConnectionApiState;
  connection: IntegrationConnection | null;
  disconnectArmed: boolean;
  disconnectBusy: boolean;
  entry: IntegrationCatalogueEntry;
  healthBusy: boolean;
  inventoryKey: string;
  oauthReturn: DesktopOAuthReturnReadiness | null;
  onClose(): void;
  onConnect(): void;
  onDisconnect(connection: IntegrationConnection): void;
  onHealth(connection: IntegrationConnection): void;
  onSubmit(submission: IntegrationSecretSubmission): Promise<boolean>;
  onToggle(): void;
  open: boolean;
  revocationBusy: boolean;
  setupBusy: boolean;
  setupOpen: boolean;
}) {
  const connected = Boolean(connection && connection.health !== "revoked");
  const health = connection ? integrationHealthPresentation(connection.health) : null;
  const certification = certificationPresentation(entry.certification);
  const method = connectionMethod(entry);
  const enabledTools = connection?.enabled_tools ?? [];
  const canStart = canStartIntegrationSetup(entry, apiState);
  const detailId = `plugin-detail-${safeDomId(entry.id)}`;

  return (
    <article className={`plugins-row ${open ? "open" : ""}`} data-plugin-key={inventoryKey}>
      <button
        aria-controls={detailId}
        aria-expanded={open}
        aria-label={`${open ? "Close" : "Open"} ${entry.label} details`}
        className="plugins-row-toggle"
        onClick={onToggle}
        type="button"
      >
        <span className={`plugins-icon ${connected ? "connected" : "available"}`}>
          <PluginGlyph kind={connected ? "plug" : "plus"} />
        </span>
        <span className="plugins-row-copy">
          <span className="plugins-row-name">
            <span>{entry.label}</span>
            {certification && (
              <span className={`plugins-certification ${certification.tone}`}>{certification.label}</span>
            )}
          </span>
          <span className={`plugins-row-sub ${connected ? "" : "muted"}`}>
            {integrationSubline(entry, connection, method.label)}
          </span>
        </span>
        <span className="plugins-row-status">
          {connected && enabledTools.length > 0 && (
            <span className="plugins-row-meta">{enabledTools.length} {enabledTools.length === 1 ? "verb" : "verbs"}</span>
          )}
          {health ? (
            <>
              <span className={`plugins-health-dot ${health.tone}`} aria-hidden />
              <span className={`plugins-health ${health.tone}`}>{health.label}</span>
            </>
          ) : (
            <span className="plugins-health method">{method.label}</span>
          )}
          <span className="plugins-caret" aria-hidden>›</span>
        </span>
      </button>

      {open && (
        <div className="plugins-row-detail" id={detailId} role="region" aria-label={`${entry.label} details`}>
          <p className="plugins-access-copy">{entry.access_copy ?? entry.description}</p>

          {enabledTools.length > 0 && (
            <div className="plugins-tool-list">
              <span>Enabled tools</span>
              <div>
                {enabledTools.map((tool) => <code key={tool}>{tool}</code>)}
              </div>
            </div>
          )}

          <div className="plugins-facts">
            <Fact label="certification" value={certificationFact(entry)} />
            {connection && <Fact label="health" value={health?.label ?? "Not reported"} tone={health?.tone} />}
            {connection && <Fact label="acting as" value={actingAs(connection)} />}
            {connection && <Fact label="checked" value={evidenceTime(connection.last_checked_at)} />}
            {connection && (
              <Fact
                label="credential"
                value={credentialScopeFact(connection)}
              />
            )}
            {!connection && <Fact label="auth" value={method.label} />}
            {!connection && <Fact label="credential" value="none requested" />}
            <Fact label="transport" value={transportLabel(entry.transport)} />
          </div>

          <div className="plugins-method">
            <strong>{connection ? `${method.label} connection` : method.label}</strong>
            <span>{connection
              ? connectedMethodCopy(entry, connection, method.label)
              : setupMethodCopy(entry, apiState, method.label, oauthReturn)}</span>
          </div>

          {connection?.health === "revoked" ? (
            <p className="plugins-guard">
              This connection record is revoked. Boltrig will not treat it as active or infer that its credential remains usable.
            </p>
          ) : connection ? (
            <div className="plugins-actions">
              <button
                className="plugins-primary-action"
                disabled={healthBusy || disconnectBusy || revocationBusy}
                onClick={() => onHealth(connection)}
                type="button"
              >
                {healthBusy ? "Checking…" : "Check it now"}
              </button>
              <button
                className={`plugins-secondary-action ${disconnectArmed ? "danger" : ""}`}
                disabled={disconnectBusy || healthBusy || revocationBusy}
                onClick={() => onDisconnect(connection)}
                type="button"
              >
                {disconnectArmed ? "Confirm revoke" : "Revoke"}
              </button>
            </div>
          ) : setupOpen && entry.setup_contract?.kind === "manual_secret" ? (
            <ManualSecretSetup
              busy={setupBusy}
              contract={entry.setup_contract}
              defaultLabel={entry.label}
              onSubmit={onSubmit}
            />
          ) : (
            <div className="plugins-actions">
              <button
                className="plugins-primary-action"
                disabled={!canStart}
                onClick={onConnect}
                title={connectTitle(entry, apiState)}
                type="button"
              >
                {setupActionLabel(entry, canStart)}
              </button>
              <button className="plugins-secondary-action" onClick={onClose} type="button">Not now</button>
            </div>
          )}
        </div>
      )}
    </article>
  );
}

function McpRow({
  inventoryKey,
  onToggle,
  open,
  server,
}: {
  inventoryKey: string;
  onToggle(): void;
  open: boolean;
  server: McpServerSummary;
}) {
  const connected = server.state !== "retired";
  const health = mcpHealthPresentation(server);
  const detailId = `plugin-detail-mcp-${safeDomId(server.id)}`;
  const toolCount = server.tool_snapshot.count;

  return (
    <article className={`plugins-row ${open ? "open" : ""}`} data-plugin-key={inventoryKey}>
      <button
        aria-controls={detailId}
        aria-expanded={open}
        aria-label={`${open ? "Close" : "Open"} ${server.id} server details`}
        className="plugins-row-toggle"
        onClick={onToggle}
        type="button"
      >
        <span className={`plugins-icon ${connected ? "connected" : "available"}`}>
          <PluginGlyph kind="code" />
        </span>
        <span className="plugins-row-copy">
          <span className="plugins-row-name"><span>{server.id}</span></span>
          <span className={`plugins-row-sub ${connected ? "" : "muted"}`}>{mcpSubline(server)}</span>
        </span>
        <span className="plugins-row-status">
          {toolCount > 0 && (
            <span className="plugins-row-meta">{toolCount} {toolCount === 1 ? "tool" : "tools"}</span>
          )}
          <span className={`plugins-health-dot ${health.tone}`} aria-hidden />
          <span className={`plugins-health ${health.tone}`}>{health.label}</span>
          <span className="plugins-caret" aria-hidden>›</span>
        </span>
      </button>

      {open && (
        <div className="plugins-row-detail" id={detailId} role="region" aria-label={`${server.id} server details`}>
          <p className="plugins-access-copy">{mcpAccessCopy(server)}</p>
          <div className="plugins-facts">
            <Fact label="state" value={server.state} />
            <Fact label="health" value={health.label} tone={health.tone} />
            <Fact
              label={server.last_probe ? "last probe" : "discovered"}
              value={evidenceTime(server.last_probe?.checked_at ?? server.tool_snapshot.observed_at)}
            />
            {server.last_probe?.failure_code && (
              <Fact label="code" value={server.last_probe.failure_code} tone="amber" />
            )}
            <Fact
              label="credential"
              value={server.credential_configured ? "configured · contents unavailable" : "not configured"}
            />
            <Fact label="snapshot" value={`${server.tool_snapshot.count} · ${server.tool_snapshot.publication_status}`} />
          </div>
          <div className="plugins-method">
            <strong>MCP server</strong>
            <span>
              {server.endpoint.origin
                ? `${server.endpoint.origin}${server.endpoint.path_redacted ? " · path redacted" : ""}`
                : "Endpoint origin is not exposed by the server projection."}
            </span>
          </div>
          <div className="plugins-actions">
            <a className="plugins-primary-action" href="#/build/adapters">Open MCP operations</a>
          </div>
        </div>
      )}
    </article>
  );
}

function CategoryFilterRow({
  active,
  count,
  label,
  onClick,
}: {
  active: boolean;
  count: number;
  label: string;
  onClick(): void;
}) {
  return (
    <button aria-label={`Filter by ${label}`} aria-pressed={active} onClick={onClick} type="button">
      <span className={`plugins-category-tick ${active ? "active" : ""}`} aria-hidden>✓</span>
      <span>{label}</span>
      <small>{count}</small>
    </button>
  );
}

function Fact({
  label,
  tone,
  value,
}: {
  label: string;
  tone?: HealthTone;
  value: string;
}) {
  return (
    <span className={`plugins-fact ${tone ? `tone-${tone}` : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </span>
  );
}

function RuntimeAddons({
  addons,
  state,
}: {
  addons: RuntimeAddon[];
  state: InventoryApiState;
}) {
  return (
    <section className="plugins-runtime-addons" aria-label="Runtime add-ons">
      <div className="plugins-runtime-heading">
        <div>
          <p>Installed extensions</p>
          <h2>Runtime add-ons</h2>
        </div>
        {state === "available" && <small>{addons.length} installed</small>}
      </div>
      {state === "loading" && (
        <p className="plugins-api-state" role="status">Checking the kernel add-on inventory…</p>
      )}
      {state === "denied" && (
        <p className="plugins-api-state" role="status">
          Add-on inventory denied. Your current session cannot read this scope.
        </p>
      )}
      {state === "unavailable" && (
        <p className="plugins-api-state" role="status">Add-on inventory unavailable.</p>
      )}
      {state === "available" && addons.length === 0 && (
        <p className="plugins-api-state" role="status">No runtime add-ons are installed in this build.</p>
      )}
      {state === "available" && addons.length > 0 && (
        <div className="plugins-runtime-grid">
          {addons.map((addon) => (
            <article className="plugins-runtime-card" key={addon.id}>
              <div className="plugins-runtime-card-heading">
                <div>
                  <h3>{addon.id}</h3>
                  <small>Version {addon.version}</small>
                </div>
                <span className={`plugins-runtime-state ${addon.runtime.status}`}>
                  {runtimeLabel(addon.runtime.status)}
                </span>
              </div>
              <p className="plugins-runtime-activation">Installed / {addon.activation}</p>
              <p>{runtimeReason(addon)}</p>
              <div className="plugins-runtime-contributions" aria-label={`${addon.id} contributions`}>
                {addon.contributions.harness && <span>Agent guidance</span>}
                {addon.contributions.adapter && <span>Adapter binding</span>}
                {addon.contributions.consequence_hint && <span>Risk mapping</span>}
                {!Object.values(addon.contributions).some(Boolean) && <span>No declared contributions</span>}
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

function inventorySearchText(item: InventoryItem): string {
  if (item.kind === "mcp") {
    return [
      item.label,
      "your own servers mcp",
      item.server.source,
      item.server.state,
      item.server.health.status,
      item.server.operability.status,
      item.server.operability.reason,
      item.server.last_probe?.failure_code,
      item.server.endpoint.origin,
      item.connected ? "connected" : "not yet",
    ].filter(Boolean).join(" ").toLowerCase();
  }
  return [
    item.label,
    groupLabel(item.category),
    item.entry.description,
    item.entry.certification,
    item.entry.transport,
    item.entry.auth.map(authLabel).join(" "),
    item.connection?.label,
    item.connection?.health,
    item.connection?.accounts.map((account) => account.label).join(" "),
    item.connection?.enabled_tools.join(" "),
    item.connected ? "connected" : "not yet",
  ].filter(Boolean).join(" ").toLowerCase();
}

function groupLabel(category: InventoryCategory): string {
  return GROUPS.find((group) => group.id === category)?.label ?? category;
}

function integrationKey(id: string): string {
  return `integration:${id}`;
}

function mcpKey(id: string): string {
  return `mcp:${id}`;
}

function safeDomId(value: string): string {
  return value.replace(/[^a-zA-Z0-9_-]/g, "-");
}

function errorStatus(error: unknown): number | null {
  if (error instanceof BoltrigApiError) return error.status;
  if (typeof error === "object" && error !== null && "status" in error && typeof error.status === "number") {
    return error.status;
  }
  return null;
}

function errorReason(error: unknown): string | null {
  const body = error instanceof BoltrigApiError
    ? error.body
    : typeof error === "object" && error !== null && "body" in error
      ? error.body
      : null;
  if (typeof body === "object" && body !== null && "reason" in body && typeof body.reason === "string") {
    return body.reason;
  }
  return null;
}

function credentialScopeFact(connection: IntegrationConnection): string {
  if (!connection.credential_ref_present) return "no reference reported";
  // Whose credential this is, said plainly. A member looking at the plugins page
  // needs to know whether a call runs as them or as the organisation, and the
  // custody phrasing stays because the reference is never exposed either way.
  if (connection.level !== "user") return "the organisation's · custody not exposed";
  return connection.is_own
    ? "yours · custody not exposed"
    : "another member's · custody not exposed";
}

function integrationHealthPresentation(health: string): HealthPresentation {
  if (health === "ok") return { label: "Connected", tone: "green" };
  if (health === "degraded") return { label: "Degraded", tone: "amber" };
  if (health === "down") return { label: "Down", tone: "red" };
  if (health === "revoked") return { label: "Revoked", tone: "red" };
  if (health === "pending") return { label: "Needs pairing", tone: "unknown" };
  return { label: "Not verified", tone: "unknown" };
}

function mcpHealthPresentation(server: McpServerSummary): HealthPresentation {
  if (server.state === "retired") return { label: "Retired", tone: "red" };
  if (server.health.status === "down" || server.operability.status === "unavailable") {
    return { label: "Unavailable", tone: "red" };
  }
  if (
    server.last_probe?.outcome === "failed"
    || server.health.status === "degraded"
    || server.operability.status === "degraded"
  ) {
    return { label: "Degraded", tone: "amber" };
  }
  if (server.state === "inert") return { label: "Inactive", tone: "unknown" };
  if (server.health.status === "ok" && server.operability.status === "ready") {
    return { label: "Connected", tone: "green" };
  }
  return { label: "Not checked", tone: "unknown" };
}

function certificationPresentation(
  certification: IntegrationCatalogueEntry["certification"],
): { label: string; tone: "neutral" | "amber" | "red" } | null {
  if (certification === "certified") return { label: "Reviewed", tone: "neutral" };
  if (certification === "certifying") return { label: "Under review", tone: "amber" };
  if (certification === "suspended") return { label: "Suspended", tone: "red" };
  return null;
}

function certificationFact(entry: IntegrationCatalogueEntry): string {
  if (entry.certification === "certified") return "reviewed";
  if (entry.certification === "certifying") return "under review";
  if (entry.certification === "suspended") return "suspended";
  return "not reviewed";
}

function connectionMethod(entry: IntegrationCatalogueEntry): { kind: IntegrationAuthKind | "none"; label: string } {
  if (entry.setup_contract?.kind === "manual_secret") return { kind: "manual_secret", label: "Provider key" };
  if (entry.auth.includes("oauth2")) return { kind: "oauth2", label: "OAuth" };
  if (entry.auth.includes("manual_secret")) return { kind: "manual_secret", label: "Provider key" };
  if (entry.auth.includes("channel_pairing")) return { kind: "channel_pairing", label: "Pairing" };
  return { kind: "none", label: "No credential" };
}

function authLabel(auth: IntegrationAuthKind): string {
  if (auth === "oauth2") return "OAuth";
  if (auth === "manual_secret") return "Provider key";
  return "Pairing";
}

function canStartIntegrationSetup(entry: IntegrationCatalogueEntry, state: ConnectionApiState): boolean {
  if (state !== "available" || !entry.available || !entry.setup_supported) return false;
  if (entry.setup_contract?.kind === "manual_secret") return true;
  return entry.auth.includes("oauth2");
}

function setupActionLabel(entry: IntegrationCatalogueEntry, canStart: boolean): string {
  if (!canStart) return "Setup unavailable";
  if (entry.setup_contract?.kind === "manual_secret") return "Add the key";
  if (entry.auth.includes("oauth2")) return `Open ${entry.label}`;
  return "Setup unavailable";
}

function integrationSubline(
  entry: IntegrationCatalogueEntry,
  connection: IntegrationConnection | null,
  method: string,
): string {
  if (connection) {
    const account = connection.accounts.find((item) => item.selected) ?? connection.accounts[0];
    return account ? `Acting as ${account.label}` : connection.label;
  }
  if (!entry.available || !entry.setup_supported) {
    return entry.availability_reason
      ? `Unavailable · ${humanReason(entry.availability_reason)}`
      : "No reviewed setup contract in this deployment";
  }
  if (method === "OAuth") return `Sign in with ${entry.label}`;
  if (method === "Provider key") return "A provider key you paste once";
  if (method === "Pairing") return "Pair through the channel setup";
  return "No credential method declared";
}

function setupMethodCopy(
  entry: IntegrationCatalogueEntry,
  apiState: ConnectionApiState,
  method: string,
  oauthReturn: DesktopOAuthReturnReadiness | null,
): string {
  if (apiState !== "available") {
    return "The connection service is unavailable, so no credential can be requested and no connection is inferred.";
  }
  if (!entry.available || !entry.setup_supported) {
    return "This deployment does not publish a reviewed setup contract for this entry. No credential will be requested.";
  }
  if (method === "Provider key" && entry.setup_contract?.kind === "manual_secret") {
    return entry.setup_copy
      ?? "Only the provider-declared fields are accepted. Secret values are submitted once; the connection projection never returns them.";
  }
  if (method === "Provider key") {
    return "A manual-secret method is declared, but no structured field contract is published. No credential will be requested.";
  }
  if (method === "OAuth") {
    const returnState = oauthReturnLabel(oauthReturn);
    return `Boltrig asks the kernel for the provider launch and shows a connection only after canonical confirmation. Current return state: ${returnState}.`;
  }
  if (method === "Pairing") {
    return "Pairing is listed, but setup is not available here. No account will be treated as paired.";
  }
  return "No authentication method is declared, so this view will not ask for a credential.";
}

function connectedMethodCopy(
  entry: IntegrationCatalogueEntry,
  connection: IntegrationConnection,
  method: string,
): string {
  const reference = connection.credential_ref_present
    ? "A credential reference is present"
    : "No credential reference is reported";
  if (method === "OAuth") {
    return `${reference}. The connection API does not expose token custody or refresh ownership, so this view does not infer either.`;
  }
  if (method === "Provider key") {
    return `${reference}. Secret contents are not returned by the connection projection.`;
  }
  if (method === "Pairing") {
    return `${reference}. Pairing state comes only from the reported connection health.`;
  }
  return `${entry.label} reports a connection, but no credential method is declared. Custody is not inferred.`;
}

function connectTitle(entry: IntegrationCatalogueEntry, state: ConnectionApiState): string | undefined {
  if (state !== "available") return "Connection service is not enabled";
  if (!entry.available) return `Unavailable: ${entry.availability_reason ?? entry.certification}`;
  if (!entry.setup_supported) return "No reviewed setup contract is configured";
  if (entry.auth.includes("manual_secret") && entry.setup_contract?.kind !== "manual_secret") {
    return "No structured secret-field contract is configured";
  }
  if (!entry.auth.includes("oauth2") && entry.setup_contract?.kind !== "manual_secret") {
    return "No supported setup operation is exposed in this view";
  }
  return undefined;
}

function actingAs(connection: IntegrationConnection): string {
  const selected = connection.accounts.filter((account) => account.selected);
  const accounts = selected.length > 0 ? selected : connection.accounts;
  if (accounts.length === 0) return "not reported";
  return accounts.map((account) => account.label).join(", ");
}

function evidenceTime(value: string | null | undefined): string {
  if (!value) return "not reported";
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return "reported · time unavailable";
  const elapsed = Date.now() - timestamp;
  if (elapsed < 0) return "reported by server";
  const minutes = Math.floor(elapsed / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function transportLabel(transport: IntegrationCatalogueEntry["transport"]): string {
  if (transport === "channel_gateway") return "channel gateway";
  return transport;
}

function mcpSubline(server: McpServerSummary): string {
  if (server.last_probe?.outcome === "failed") {
    const code = server.last_probe.failure_code;
    return code
      ? `Last probe failed · ${mcpFailureLabel(code)}`
      : "Last probe failed · no failure code reported";
  }
  if (server.tool_snapshot.status === "never_discovered") {
    return "No successful discovery snapshot reported";
  }
  return `${server.tool_snapshot.count} ${server.tool_snapshot.count === 1 ? "tool" : "tools"} · discovered ${evidenceTime(server.tool_snapshot.observed_at)}`;
}

function mcpAccessCopy(server: McpServerSummary): string {
  if (server.last_probe?.outcome === "failed") {
    return "The last probe failed. This view preserves the durable snapshot exactly as reported and does not infer current tool availability from a failed probe.";
  }
  if (server.tool_snapshot.status === "never_discovered") {
    return "The server has not reported a successful discovery snapshot, so this view does not claim that any tools are available.";
  }
  return "Tool count and availability come from the server's latest successful check. Actions still follow your approval settings.";
}

function mcpIssueSummary(server: McpServerSummary): string | null {
  if (server.state === "retired") return null;
  if (server.last_probe?.outcome === "failed") {
    return server.last_probe.failure_code
      ? `${server.id}'s last probe failed (${mcpFailureLabel(server.last_probe.failure_code)})`
      : `${server.id}'s last probe failed`;
  }
  if (server.health.status === "down") return `${server.id} reports down`;
  if (server.operability.status === "unavailable") return `${server.id} reports unavailable`;
  if (server.health.status === "degraded" || server.operability.status === "degraded") {
    return `${server.id} reports degraded`;
  }
  return null;
}

function mcpFailureLabel(code: string): string {
  const labels: Record<string, string> = {
    credential_unavailable: "credential unavailable",
    egress_denied: "egress denied",
    transport_unavailable: "transport unavailable",
    protocol_invalid: "invalid protocol response",
    discovery_invalid: "invalid discovery response",
    unexpected_failure: "unexpected failure",
  };
  return labels[code] ?? humanReason(code);
}

function humanReason(value: string): string {
  return value.replaceAll("_", " ");
}

function joinIssueSummaries(items: string[]): string {
  if (items.length <= 1) return items[0] ?? "";
  if (items.length === 2) return `${items[0]}, and ${items[1]}`;
  return `${items.slice(0, -1).join(", ")}, and ${items.at(-1)}`;
}

function oauthReturnLabel(readiness: DesktopOAuthReturnReadiness | null): string {
  if (!readiness) return "checking";
  if (readiness.runtime === "web") return "browser callback unavailable";
  if (readiness.state !== "ready") return "native callback unavailable";
  return "native return ready · provider exchange unavailable";
}

function SearchIcon() {
  return (
    <svg aria-hidden fill="none" height="15" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" viewBox="0 0 24 24" width="15">
      <circle cx="11" cy="11" r="6.5" />
      <path d="M15.8 15.8 20 20" />
    </svg>
  );
}

function FilterIcon() {
  return (
    <svg aria-hidden fill="none" height="14" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" viewBox="0 0 24 24" width="14">
      <path d="M4 7h16M7 12h10M10 17h4" />
    </svg>
  );
}

function PluginGlyph({ kind }: { kind: "plus" | "plug" | "code" }) {
  const paths = kind === "plus"
    ? ["M12 5v14M5 12h14"]
    : kind === "code"
      ? ["M8.5 7.5L4 12l4.5 4.5M15.5 7.5L20 12l-4.5 4.5"]
      : ["M8 3v5M16 3v5", "M5.5 8h13v3a6.5 6.5 0 0 1-13 0z", "M12 17.5V21"];
  return (
    <svg aria-hidden fill="none" height="15" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" viewBox="0 0 24 24" width="15">
      {paths.map((path) => <path d={path} key={path} />)}
    </svg>
  );
}
