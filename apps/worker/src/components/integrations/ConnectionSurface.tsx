import type { IntegrationConnection } from "@wlilley93/boltrig-web-sdk";

/**
 * What a connected plugin can actually do, in both vocabularies.
 *
 * `enabled_tools` is the provider's own: `opbox.create_matter`. It is what the
 * row counted, and it stopped being the honest answer when the capability layer
 * landed, because a provider-prefixed verb id is not what a model is ever
 * offered. `enabled_capabilities` is the canonical set, from APPROVED bindings
 * only, so a proposed mapping is invisible here exactly as it is invisible to
 * routing. The kernel has sent it since the capability layer shipped and no
 * TypeScript read it.
 *
 * BOTH are shown in the detail, and the canonical one leads. An operator
 * debugging a connection needs the provider's names; an operator reasoning
 * about what an agent can do needs the canonical ones, and collapsing the two
 * into one list would make the smaller number look like a truncation of the
 * larger.
 */

function count(items: string[], singular: string, plural: string): string {
  return `${items.length} ${items.length === 1 ? singular : plural}`;
}

/** The one-line summary on the row. Null when there is nothing to report. */
export function connectionRowMeta(
  connection: IntegrationConnection | null | undefined,
): string | null {
  if (!connection) return null;
  const capabilities = connection.enabled_capabilities;
  // Absent, not empty: a kernel older than the capability layer omits the
  // field entirely, and reporting "no capabilities" there would describe a
  // connection with no surface at all rather than one we cannot ask.
  if (capabilities === undefined) {
    const tools = connection.enabled_tools ?? [];
    return tools.length === 0 ? null : count(tools, "verb", "verbs");
  }
  if (capabilities.length > 0) return count(capabilities, "capability", "capabilities");
  const tools = connection.enabled_tools ?? [];
  // Tools but no capabilities is a real and common state: the operations are
  // registered and nothing has been mapped or approved yet. Saying "0
  // capabilities" would read as broken; naming the verbs says what is true.
  return tools.length === 0 ? null : `${count(tools, "verb", "verbs")}, none mapped`;
}

export function ConnectionSurfaceList({
  connection,
}: {
  connection: IntegrationConnection | null;
}) {
  const capabilities = connection?.enabled_capabilities ?? [];
  const tools = connection?.enabled_tools ?? [];
  if (capabilities.length === 0 && tools.length === 0) return null;
  return (
    <>
      {capabilities.length > 0 && (
        <div className="plugins-tool-list">
          <span>Capabilities an agent can use</span>
          <div>
            {capabilities.map((id) => <code key={id}>{id}</code>)}
          </div>
        </div>
      )}
      {tools.length > 0 && (
        <div className="plugins-tool-list">
          <span>Enabled tools</span>
          <div>
            {tools.map((tool) => <code key={tool}>{tool}</code>)}
          </div>
        </div>
      )}
    </>
  );
}
