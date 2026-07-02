import { useMemo, useState } from "react";

import { api } from "../api/client";
import type { DeckCol } from "../deck/Deck";
import { navigate } from "../router";
import { useFetch } from "../useFetch";
import { ByChat, CoachMark, GrantList } from "./uxFlow";
import { EmptyState, FetchError, InfoCallout, PageIntro, StatusBadge, CONSEQUENCE } from "./ux";
import {
  agentColumns,
  budgetPct,
  deniedOf,
  enrichAgents,
  readAgentSpecs,
} from "./agents/model";

export function useAgentDeckCols(): DeckCol[] {
  const hierarchy = useFetch(() => api.getConfig("hierarchy"), []);
  const pool = useFetch(() => api.getConfig("ephemeral_runtimes"), []);
  return useMemo(() => {
    if (deniedOf(hierarchy.data) || deniedOf(pool.data)) return [];
    return agentColumns(readAgentSpecs(hierarchy.data, pool.data));
  }, [hierarchy.data, pool.data]);
}

function kindLabel(kind: string): string {
  if (kind === "chief") return "chief of staff";
  if (kind === "head") return "department head";
  return "worker profile";
}

function AgentNode({
  agent,
  selected,
  onSelect,
}: {
  agent: ReturnType<typeof enrichAgents>[number];
  selected: boolean;
  onSelect: () => void;
}) {
  const pct = budgetPct(agent.budget);
  const open = () => navigate(`/agents/${encodeURIComponent(agent.name)}`);
  return (
    <button
      type="button"
      className={`ag-node ag-node--${agent.kind} ${selected ? "ag-node--selected" : ""}`}
      aria-pressed={selected}
      onClick={onSelect}
      onDoubleClick={open}
      onKeyDown={(e) => {
        if (e.key === "Enter" && selected) {
          e.preventDefault();
          open();
        }
      }}
      title={`Open ${agent.name}`}
    >
      <span className="ag-node__kind">{kindLabel(agent.kind)}</span>
      <strong className="ag-node__name">{agent.name}</strong>
      {agent.department && <span className="ag-node__dept">{agent.department}</span>}
      <span className="ag-node__facts">
        <span>{agent.runtime}</span>
        <span>{agent.model_endpoint ?? "default model"}</span>
        <span>depth {agent.max_depth}</span>
      </span>
      <span className="ag-node__chips">
        <span className="badge">{agent.cost_tier}</span>
        <span className="badge">{agent.matchedSkills.length} skills</span>
        <span className="badge">{agent.effectiveVerbs.length} verbs</span>
        {agent.boundVerbs.length > 0 && (
          <span className="badge badge--conseq-low">{agent.boundVerbs.length} bound</span>
        )}
      </span>
      {pct !== null && (
        <span className="ag-budget" title="Department budget used">
          <span className="ag-budget__fill" style={{ width: `${pct}%` }} />
        </span>
      )}
    </button>
  );
}

function FactsStrip({
  agent,
}: {
  agent: ReturnType<typeof enrichAgents>[number] | undefined;
}) {
  if (!agent) return null;
  return (
    <aside className="ag-facts" aria-label="Selected agent">
      <div>
        <span className="badge">{kindLabel(agent.kind)}</span>{" "}
        <code>{agent.name}</code>
        <span className="ag-facts__muted">
          {" "}
          {agent.runtime} / {agent.model_endpoint ?? "default"} / depth {agent.max_depth}
        </span>
      </div>
      <div className="ag-facts__metrics">
        <span>{agent.matchedSkills.length} matched skills</span>
        <span>{agent.effectiveGrants.length} grants</span>
        <span>{agent.effectiveVerbs.length} callable verbs</span>
        <span>{agent.workItems.length} work items</span>
      </div>
      <button
        type="button"
        className="btn btn--sm"
        onClick={() => navigate(`/agents/${encodeURIComponent(agent.name)}`)}
      >
        Open agent
      </button>
    </aside>
  );
}

export function AgentsSlide() {
  const hierarchy = useFetch(() => api.getConfig("hierarchy"), []);
  const pool = useFetch(() => api.getConfig("ephemeral_runtimes"), []);
  const skills = useFetch(() => api.skills(), []);
  const caps = useFetch(() => api.capabilities(), []);
  const budgets = useFetch(() => api.budgets(), [], 30000);
  const work = useFetch(() => api.work(), [], 30000);
  const [selected, setSelected] = useState<string | null>(null);

  const denied = deniedOf(hierarchy.data) ?? deniedOf(pool.data);
  const specs = useMemo(
    () => readAgentSpecs(hierarchy.data, pool.data),
    [hierarchy.data, pool.data],
  );
  const agents = useMemo(
    () =>
      enrichAgents(
        specs,
        skills.data?.skills ?? [],
        caps.data?.verbs ?? [],
        budgets.data?.budgets ?? [],
        work.data?.items ?? [],
      ),
    [specs, skills.data, caps.data, budgets.data, work.data],
  );
  const chief = agents.find((a) => a.kind === "chief");
  const heads = agents.filter((a) => a.kind === "head");
  const workers = agents.filter((a) => a.kind === "worker");
  const selectedAgent = agents.find((a) => a.name === selected) ?? chief ?? agents[0];

  const loading =
    (hierarchy.loading && !hierarchy.data) || (pool.loading && !pool.data);
  const empty = !loading && !denied && agents.length === 0;

  return (
    <section className="panel ag-slide">
      <PageIntro
        title="Agents"
        lead="A structured view of the durable org and the worker profiles it can convene."
        how="Open a card to inspect skills, callable verbs, budget context and work ownership. Capability changes use the governed control plane."
        actions={
          <>
            <ByChat phrase="Show me the agent org, their skills, and the worker pool." />
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => navigate("/studio")}
              title="Agent creation is a governed capability write. The full guided creator lands with the capability registry read."
            >
              New agent
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => {
                hierarchy.reload();
                pool.reload();
                skills.reload();
                caps.reload();
              }}
            >
              Refresh
            </button>
          </>
        }
      />

      <CoachMark id="boltrig.coach.agents-org">
        Each card is an agent profile. Select one to see live facts, or open it
        for the full slide.
      </CoachMark>

      {loading && <p className="muted">Loading the org...</p>}
      <FetchError error={hierarchy.error} status={hierarchy.errorStatus} onRetry={hierarchy.reload} />
      {!hierarchy.error && (
        <FetchError error={pool.error} status={pool.errorStatus} onRetry={pool.reload} />
      )}

      {denied && !loading && (
        <InfoCallout tone="warn" title="No access to the agent org">
          The server declined this read ({denied}). Ask an admin to widen your
          access.
        </InfoCallout>
      )}

      {empty && (
        <EmptyState
          title="No agent hierarchy configured"
          body="The hierarchy and worker pool config sections are empty for this organisation."
          action={
            <button type="button" className="btn" onClick={() => navigate("/admin")}>
              Open Admin
            </button>
          }
        />
      )}

      {!denied && agents.length > 0 && (
        <>
          <div className="ag-counts" aria-label="Agent counts">
            <span>{chief ? "1" : "0"} chief</span>
            <span>{heads.length} departments</span>
            <span>{workers.length} worker profiles</span>
            {caps.data?.verbs && <span>{caps.data.verbs.length} scoped verbs visible</span>}
          </div>

          <div className="ag-chart" aria-label="Agent org chart">
            {chief && (
              <div className="ag-chart__row ag-chart__row--chief">
                <AgentNode
                  agent={chief}
                  selected={selectedAgent?.name === chief.name}
                  onSelect={() => setSelected(chief.name)}
                />
              </div>
            )}

            {heads.length > 0 && (
              <div className="ag-chart__row ag-chart__row--heads">
                {heads.map((agent) => (
                  <AgentNode
                    key={agent.name}
                    agent={agent}
                    selected={selectedAgent?.name === agent.name}
                    onSelect={() => setSelected(agent.name)}
                  />
                ))}
              </div>
            )}

            {workers.length > 0 && (
              <div className="ag-worker-band">
                <div className="ag-worker-band__head">
                  <strong>Worker pool</strong>
                  <span>
                    Ephemeral profiles are chosen per task and discarded after
                    the run.
                  </span>
                </div>
                <div className="ag-chart__row ag-chart__row--workers">
                  {workers.map((agent) => (
                    <AgentNode
                      key={agent.name}
                      agent={agent}
                      selected={selectedAgent?.name === agent.name}
                      onSelect={() => setSelected(agent.name)}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>

          <FactsStrip agent={selectedAgent} />

          {selectedAgent && selectedAgent.effectiveGrants.length > 0 && (
            <div className="ag-anchor-grants">
              <span className="muted">Selected effective grants</span>
              <GrantList grants={selectedAgent.effectiveGrants.slice(0, 8)} />
            </div>
          )}

          {selectedAgent?.boundVerbs.some((verb) => verb.consequence === "high") && (
            <InfoCallout tone="consequence" title="High consequence bindings">
              This selected agent fulfils at least one high-consequence verb. The
              kernel still pauses those calls for approval.
            </InfoCallout>
          )}

          {selectedAgent?.boundVerbs.slice(0, 3).map((verb) => (
            <span className="ag-bound-preview" key={verb.id}>
              <code>{verb.id}</code>
              <StatusBadge value={verb.consequence} glossary={CONSEQUENCE} />
            </span>
          ))}
        </>
      )}
    </section>
  );
}
