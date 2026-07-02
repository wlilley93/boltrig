// Beat 1 INTERIM agents anchor: a read-only listing of the durable agent org
// (manifest hierarchy: one tier1 chief over the tier2 department heads) plus
// the ephemeral runtime pool the fleet spawns workers from. A real org chart
// with per-agent slides replaces this in Beat 2; this stays lean but honest -
// it reflects the live admin config, never a hardcoded chart. The config read
// is author-gated server-side; a denial renders calmly (the AdminPanel
// pattern: check status === "denied" / error on the tolerated response).

import { api } from "../api/client";
import type { ConfigSectionResponse } from "../api/types";
import { useFetch } from "../useFetch";
import { EmptyState, FetchError, Hint, InfoCallout, PageIntro } from "./ux";

// The manifest agent shape (hierarchy tier1/tier2 and ephemeral_runtimes
// entries share it). Config is data: every field is optional and the coercers
// below render defensively rather than trusting the wire.
interface AgentSpec {
  name?: string;
  department?: string;
  runtime?: string;
  model_endpoint?: string;
  cost_tier?: string;
  max_depth?: number;
  supported_skills?: string[];
}

function str(v: unknown): string | undefined {
  return typeof v === "string" && v ? v : undefined;
}

function strList(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((s): s is string => typeof s === "string") : [];
}

function asRecord(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : null;
}

function toAgent(v: unknown): AgentSpec | null {
  const r = asRecord(v);
  if (!r) return null;
  return {
    name: str(r.name),
    department: str(r.department),
    runtime: str(r.runtime),
    model_endpoint: str(r.model_endpoint),
    cost_tier: str(r.cost_tier),
    max_depth: typeof r.max_depth === "number" ? r.max_depth : undefined,
    supported_skills: strList(r.supported_skills),
  };
}

// getConfig tolerates non-2xx, so a 403 arrives as data, not a throw: the
// kernel answers { status: "denied", reason } (or { error } when the admin
// surface is unavailable) - exactly what AdminPanel checks.
function deniedOf(res: ConfigSectionResponse | null): string | null {
  if (!res) return null;
  if (res.status === "denied" || res.error) {
    return res.reason ?? res.error ?? "admin_forbidden";
  }
  return null;
}

function AgentCard({
  agent,
  tier,
}: {
  agent: AgentSpec;
  tier: "chief" | "head";
}) {
  const skills = agent.supported_skills ?? [];
  return (
    <article className={`org-card ${tier === "chief" ? "org-card--chief" : ""}`.trim()}>
      <div className="org-card__top">
        <span className="org-card__name">{agent.name ?? "(unnamed)"}</span>
        <span className="badge">{tier === "chief" ? "tier 1" : "tier 2"}</span>
      </div>
      <dl className="org-card__meta">
        {agent.department && (
          <>
            <dt>department</dt>
            <dd>{agent.department}</dd>
          </>
        )}
        <dt>runtime</dt>
        <dd>{agent.runtime ?? "unknown"}</dd>
        <dt>model</dt>
        <dd>{agent.model_endpoint ?? "default"}</dd>
        <dt>cost tier</dt>
        <dd>{agent.cost_tier ?? "standard"}</dd>
      </dl>
      {skills.length > 0 && (
        <div className="org-card__skills">
          {skills.map((s) => (
            <code className="tag" key={s} title="Skill pattern this agent may run">
              {s}
            </code>
          ))}
        </div>
      )}
    </article>
  );
}

export function AgentsSlide() {
  const hier = useFetch(() => api.getConfig("hierarchy"), []);
  const pool = useFetch(() => api.getConfig("ephemeral_runtimes"), []);

  const denied = deniedOf(hier.data) ?? deniedOf(pool.data);

  const hierValue = asRecord(hier.data?.value);
  const chief = toAgent(hierValue?.tier1 ?? null);
  const tier2Raw = hierValue?.tier2;
  const heads = (Array.isArray(tier2Raw) ? tier2Raw : [])
    .map(toAgent)
    .filter((a): a is AgentSpec => a !== null);
  const poolRaw = pool.data?.value;
  const runtimes = (Array.isArray(poolRaw) ? poolRaw : [])
    .map(toAgent)
    .filter((a): a is AgentSpec => a !== null);

  const loading = (hier.loading && !hier.data) || (pool.loading && !pool.data);
  const emptyOrg =
    !loading && !denied && !hier.error && !chief && heads.length === 0;

  return (
    <section className="panel">
      <PageIntro
        title="Agents"
        lead="The durable agent org: one chief of staff over the department heads, plus the ephemeral worker pool they spawn from."
        how="This reflects the live hierarchy configuration. Agents are configured in the manifest (see Admin); per-agent slides arrive in the next beat."
        actions={
          <button
            className="btn"
            onClick={() => {
              hier.reload();
              pool.reload();
            }}
          >
            Refresh
          </button>
        }
      />

      {loading && <p className="muted">Loading the org...</p>}
      <FetchError error={hier.error} status={hier.errorStatus} onRetry={hier.reload} />
      {!hier.error && (
        <FetchError error={pool.error} status={pool.errorStatus} onRetry={pool.reload} />
      )}

      {denied && !loading && (
        <InfoCallout tone="warn" title="No access to the agent org">
          The server declined this read ({denied}). Ask an admin to widen your
          access.
        </InfoCallout>
      )}

      {emptyOrg && (
        <EmptyState
          title="No agent hierarchy configured"
          body="The hierarchy section is empty for this organisation. Configure tier1 / tier2 in the Admin console's manifest."
        />
      )}

      {!denied && chief && (
        <>
          <h3 className="org-tier">Tier 1 - chief</h3>
          <div className="org-grid">
            <AgentCard agent={chief} tier="chief" />
          </div>
        </>
      )}

      {!denied && heads.length > 0 && (
        <>
          <h3 className="org-tier">Tier 2 - department heads</h3>
          <div className="org-grid">
            {heads.map((a, i) => (
              <AgentCard agent={a} tier="head" key={a.name ?? i} />
            ))}
          </div>
        </>
      )}

      {!denied && runtimes.length > 0 && (
        <>
          <h3 className="org-tier">Ephemeral runtime pool</h3>
          <div className="org-pool">
            {runtimes.map((r, i) => (
              <span className="org-pool__item" key={r.name ?? i}>
                <span className="org-pool__name">{r.name ?? "(unnamed)"}</span>
                <span>{r.runtime ?? "?"}</span>
                {r.model_endpoint && <code className="tag">{r.model_endpoint}</code>}
                {r.cost_tier && <span className="badge">{r.cost_tier}</span>}
              </span>
            ))}
          </div>
        </>
      )}

      {!denied && !loading && (
        <Hint>
          Cards are read-only in this beat - per-agent slides (one column per
          agent, to the right of this anchor) arrive next.
        </Hint>
      )}
    </section>
  );
}
