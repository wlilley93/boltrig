import {
  WORKER_INTEGRATION_CATALOGUE,
  normalizeEvents,
  type ChatMessage,
  type IntegrationCatalogueEntry,
  type ToolEntry,
} from "@wlilley93/boltrig-web-sdk";

const TOOL_SEPARATOR = "[._:/-]";
const INTEGRATIONS: ReadonlyArray<readonly [RegExp, IntegrationCatalogueEntry]> =
  WORKER_INTEGRATION_CATALOGUE.map((entry) => {
    const id = entry.id
      .split("-")
      .map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
      .join(`${TOOL_SEPARATOR}+`);
    return [new RegExp(`(^|${TOOL_SEPARATOR})${id}(${TOOL_SEPARATOR}|$)`), entry] as const;
  });

/** Match only an explicit, boundary-delimited catalogue id in the observed
 * tool verb. A human-readable label or tool argument is not enough evidence
 * to claim that an integration participated in the turn. */
export function integrationForToolVerb(
  verb: string,
): IntegrationCatalogueEntry | null {
  const value = verb.trim().toLowerCase();
  return INTEGRATIONS.find(([pattern]) => pattern.test(value))?.[1] ?? null;
}

/** The right rail is a compact projection of the exact tool receipts. Keep
 * catalogue order stable, dedupe repeated calls, and never manufacture a
 * source from assistant prose. */
export function integrationsUsedByTools(
  tools: readonly ToolEntry[],
): IntegrationCatalogueEntry[] {
  const used = new Map<string, IntegrationCatalogueEntry>();
  for (const tool of tools) {
    const integration = integrationForToolVerb(tool.verb);
    if (integration) used.set(integration.id, integration);
  }
  return [...used.values()];
}

/** Sources are conversation-wide evidence, unlike the task rail's current-run
 * process/status rows. Keep an integration visible when a later turn has no
 * call to it, while still deriving the list exclusively from persisted or
 * currently streamed tool receipts. */
export function integrationsUsedByConversation(
  messages: readonly ChatMessage[],
  liveTools: readonly ToolEntry[] = [],
): IntegrationCatalogueEntry[] {
  const tools = messages.flatMap((message) => (
    message.events?.length ? normalizeEvents(message.events).tools : []
  ));
  return integrationsUsedByTools([...tools, ...liveTools]);
}
