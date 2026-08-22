import { useEffect, useState } from "react";
import type { CapabilityCatalogueEntry } from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";

/**
 * What this tenant can actually do, named canonically.
 *
 * The Connections tab answers "what have we wired up" in the provider's own
 * vocabulary (`opbox.create_matter`). This answers "what can be asked for"
 * (`matter.open`), which is the only vocabulary a model ever sees. Two
 * connections can serve one capability and one connection can serve several,
 * so the two counts are genuinely different questions and the page shows both
 * rather than picking one and calling it the total.
 *
 * There is no capability table: a capability exists because bindings claim it,
 * so every number here is a rollup and none of them is stored.
 */
export function CapabilityCataloguePanel() {
  const [entries, setEntries] = useState<CapabilityCatalogueEntry[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "unavailable">("loading");

  useEffect(() => {
    let live = true;
    client.capabilityCatalogue()
      .then((result) => {
        if (!live) return;
        setEntries(result.capabilities);
        setState("ready");
      })
      .catch(() => {
        if (live) setState("unavailable");
      });
    return () => {
      live = false;
    };
  }, []);

  const routable = entries.filter((entry) => entry.approved > 0).length;

  return (
    <section aria-labelledby="capability-catalogue-heading" className="plugins-inventory">
      <div className="plugins-inventory-heading">
        <h2 id="capability-catalogue-heading">Capabilities</h2>
        <span>
          {state === "ready"
            ? `${routable} routable of ${entries.length}`
            : " "}
        </span>
      </div>

      {state === "loading" && <p className="plugins-empty">Loading capabilities…</p>}
      {state === "unavailable" && (
        <p className="plugins-empty">
          The capability catalogue is unavailable. No capability is assumed to
          be routable.
        </p>
      )}
      {state === "ready" && entries.length === 0 && (
        <p className="plugins-empty">
          No capabilities yet. One appears when a connected provider&rsquo;s
          operation is mapped to a canonical name.
        </p>
      )}

      <ul className="capability-list">
        {entries.map((entry) => (
          <li className="capability-row" key={entry.capability_id}>
            <div className="capability-row-copy">
              <span className="capability-row-name">
                <strong>{entry.capability_id}</strong>
                {entry.approved === 0 && (
                  <span className="plugins-health method">not routable</span>
                )}
                {entry.needs_review > 0 && (
                  <span className="plugins-health amber">
                    {entry.needs_review} to review
                  </span>
                )}
              </span>
              <span className="capability-row-sub">
                {entry.approved} of {entry.implementations}
                {entry.implementations === 1 ? " implementation" : " implementations"}
                {" approved"}
                {entry.providers.length > 0 && ` · ${entry.providers.join(", ")}`}
              </span>
              <span className="capability-row-sub muted">
                {entry.routing_policies === 0
                  ? "No rule: selection falls to binding priority"
                  : `${entry.routing_policies} ${entry.routing_policies === 1 ? "rule" : "rules"}`}
              </span>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
