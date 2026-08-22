import { useEffect, useState } from "react";
import type { RoutingPolicyView } from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";

/**
 * Which implementation a canonical verb reaches.
 *
 * With no rule, selection falls through to binding priority, which is a real
 * answer and not an error: most tenants have one implementation per capability
 * and never need a rule. The panel says so explicitly rather than showing an
 * empty table, because "no rules" and "routing is unconfigured" look identical
 * and mean different things.
 *
 * READ ONLY for now. `control.routing_policy.upsert` and `.delete` exist and
 * are governed, but authoring a rule needs a binding picker per capability, and
 * shipping a half-built editor that can write a rule it cannot show would be
 * worse than shipping the list.
 */

function scopeLabel(policy: RoutingPolicyView): string {
  return policy.scope === "workspace"
    ? `workspace ${policy.workspace_id ?? ""}`.trim()
    : "whole organisation";
}

export function RoutingRulesPanel() {
  const [policies, setPolicies] = useState<RoutingPolicyView[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "unavailable">("loading");

  useEffect(() => {
    let live = true;
    client.routingPolicies()
      .then((result) => {
        if (!live) return;
        setPolicies(result.routing_policies);
        setState("ready");
      })
      .catch(() => {
        if (live) setState("unavailable");
      });
    return () => {
      live = false;
    };
  }, []);

  return (
    <section aria-labelledby="routing-rules-heading" className="plugins-inventory">
      <div className="plugins-inventory-heading">
        <h2 id="routing-rules-heading">Rules</h2>
        <span>{state === "ready" ? `${policies.length} in force` : " "}</span>
      </div>

      {state === "loading" && <p className="plugins-empty">Loading rules…</p>}
      {state === "unavailable" && (
        <p className="plugins-empty">
          Routing rules are unavailable. No selection is assumed.
        </p>
      )}
      {state === "ready" && policies.length === 0 && (
        <p className="plugins-empty">
          No rules. Every capability is served by its highest-priority approved
          binding, which is the right answer while each has only one.
        </p>
      )}

      <ul className="capability-list">
        {policies.map((policy) => (
          <li className="capability-row" key={policy.id}>
            <div className="capability-row-copy">
              <span className="capability-row-name">
                <strong>{policy.capability_id}</strong>
                <span className="plugins-health method">{policy.operation_class}</span>
              </span>
              <span className="capability-row-sub">
                selects {policy.binding_id} for the {scopeLabel(policy)}
              </span>
              <span className="capability-row-sub muted">
                precedence {policy.precedence}
                {policy.capability_version === null
                  ? " · any version"
                  : ` · version ${policy.capability_version} only`}
              </span>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
