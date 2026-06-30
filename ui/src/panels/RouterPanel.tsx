// US-UI-01 / US-UI-03: the capability router. Lists nouns and, per noun, their
// verbs with consequence, binding target (when present) and live adapter health
// cross-referenced from /healthz. Every later-added field is treated as optional.
//
// Two views over the same caller-scoped /v1/capabilities read: "List" (the flat
// noun -> verb browser, the safe default) and "Tree" (RegistryCanvas, the React
// Flow Capability plane: noun -> verb -> binding). Both share these fetches; the
// resolveHealth / badge helpers below are exported so the canvas reuses them.

import { useMemo, useState } from "react";

import { api } from "../api/client";
import type { AdapterHealth, HealthResponse, VerbInfo } from "../api/types";
import { useIdentity } from "../identity";
import { useFetch } from "../useFetch";
import { RegistryCanvas } from "./RegistryCanvas";
import { CONSEQUENCE, InfoCallout, PageIntro } from "./ux";

const HEALTH_TIP: Record<string, string> = {
  ok: "This service is healthy.",
  degraded: "Working, but the service is unhealthy.",
  down: "This service is down.",
  unknown: "No health info, or no runtime bound to this verb yet.",
};

const HEALTH_VALUES: ReadonlySet<string> = new Set([
  "ok",
  "degraded",
  "down",
  "unknown",
]);

export function bindingOf(verb: VerbInfo): string | undefined {
  return verb.binding?.target_ref;
}

// Resolve a verb's adapter health from its own field or from the /healthz map,
// which is keyed "<tenant>/<adapterId>".
export function resolveHealth(
  verb: VerbInfo,
  health: HealthResponse | null,
  tenant: string,
): AdapterHealth {
  if (typeof verb.health === "string" && HEALTH_VALUES.has(verb.health)) {
    return verb.health as AdapterHealth;
  }
  if (!health) return "unknown";
  const candidate = bindingOf(verb);
  if (!candidate) return "unknown";

  const direct = health.adapters[candidate];
  if (direct) return direct;
  const scoped = health.adapters[`${tenant}/${candidate}`];
  if (scoped) return scoped;
  for (const [key, value] of Object.entries(health.adapters)) {
    if (key === candidate || key.split("/").pop() === candidate) return value;
  }
  return "unknown";
}

export function HealthBadge({ health }: { health: AdapterHealth }) {
  return (
    <span className={`badge badge--health badge--${health}`} title={HEALTH_TIP[health]}>
      {health}
    </span>
  );
}

export function ConsequenceBadge({ value }: { value?: string }) {
  const v = value ?? "unknown";
  const term = CONSEQUENCE[v];
  return (
    <span className={`badge badge--conseq badge--conseq-${v}`} title={term?.tip}>
      {term ? term.label.replace(" consequence", "") : v}
    </span>
  );
}

type RouterView = "list" | "tree";

export function RouterPanel() {
  const identity = useIdentity();
  const caps = useFetch(() => api.capabilities(), [], 0);
  const health = useFetch(() => api.health(), [], 15000);
  // "list" is the safe default; "tree" is the visual Capability plane.
  const [view, setView] = useState<RouterView>("list");

  const grouped = useMemo(() => {
    const verbs = caps.data?.verbs ?? [];
    const byNoun = new Map<string, VerbInfo[]>();
    for (const v of verbs) {
      const noun = v.noun || "(unspecified)";
      const bucket = byNoun.get(noun);
      if (bucket) bucket.push(v);
      else byNoun.set(noun, [v]);
    }
    return [...byNoun.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [caps.data]);

  return (
    <section className="panel">
      <PageIntro
        title="Router"
        lead="Everything your identity is allowed to do."
        how="A noun is a thing (ticket, invoice); a verb is an action on it (ticket.read). The binding is what actually runs the verb; the health dot is that service's status."
        actions={
          <>
            <span className="muted">
              {caps.data ? `${caps.data.verbs.length} actions` : ""}
            </span>
            <div className="seg" role="group" aria-label="Router view">
              <button
                className={`btn btn--seg ${view === "list" ? "btn--seg-on" : ""}`}
                onClick={() => setView("list")}
              >
                List
              </button>
              <button
                className={`btn btn--seg ${view === "tree" ? "btn--seg-on" : ""}`}
                onClick={() => setView("tree")}
              >
                Tree
              </button>
            </div>
            <button
              className="btn"
              onClick={() => {
                caps.reload();
                health.reload();
              }}
            >
              Refresh
            </button>
          </>
        }
      />

      <InfoCallout>
        <span>
          <strong className="is-warn">High</strong> consequence (amber) means a
          verb is high-stakes and may pause for approval; <strong>low</strong> is
          routine. The health dot shows whether the service behind a verb is up.
        </span>
      </InfoCallout>

      {caps.loading && !caps.data && <p className="muted">Loading...</p>}
      {caps.error && <p className="error">Could not load capabilities: {caps.error}</p>}
      {health.error && (
        <p className="warn">
          Health unavailable ({health.error}); showing adapter health as unknown.
        </p>
      )}

      {view === "tree" ? (
        <RegistryCanvas
          verbs={caps.data?.verbs ?? []}
          health={health.data}
          tenant={identity.tenant}
        />
      ) : (
        <RouterList
          grouped={grouped}
          health={health.data}
          tenant={identity.tenant}
          caps={caps}
          grants={identity.grants}
        />
      )}
    </section>
  );
}

function RouterList({
  grouped,
  health,
  tenant,
  caps,
  grants,
}: {
  grouped: [string, VerbInfo[]][];
  health: HealthResponse | null;
  tenant: string;
  caps: { loading: boolean; error: string | null };
  grants: string;
}) {
  return (
    <>
      {grouped.length === 0 && !caps.loading && !caps.error && (
        <p className="muted">
          No actions are visible for this identity. Your grants (
          <code className="mono">{grants || "none"}</code>) decide what appears -
          switch identity in the sidebar, or ask an admin to widen your scope.
        </p>
      )}

      <div className="router__nouns">
        {grouped.map(([noun, verbs]) => (
          <div className="noun-card" key={noun}>
            <div className="noun-card__head">
              <h3>{noun}</h3>
              <span className="muted">{verbs.length} verb(s)</span>
            </div>
            <ul className="verb-list">
              {verbs
                .slice()
                .sort((a, b) => a.id.localeCompare(b.id))
                .map((v) => {
                  const binding = bindingOf(v);
                  const h = resolveHealth(v, health, tenant);
                  return (
                    <li className="verb-row" key={v.id}>
                      <div className="verb-row__main">
                        <code className="verb-row__id">{v.id}</code>
                        <ConsequenceBadge value={v.consequence} />
                      </div>
                      <div className="verb-row__meta">
                        {binding ? (
                          <span className="muted">
                            runs via <code>{binding}</code>
                          </span>
                        ) : (
                          <span
                            className="muted ux-termtip"
                            title="No runtime bound yet - this verb is declared but not wired to an adapter or agent."
                          >
                            not wired yet
                          </span>
                        )}
                        <HealthBadge health={h} />
                      </div>
                    </li>
                  );
                })}
            </ul>
          </div>
        ))}
      </div>
    </>
  );
}
