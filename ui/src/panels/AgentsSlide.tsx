import { useMemo } from "react";

import { api } from "../api/client";
import type { DeckCol } from "../deck/Deck";
import { navigate } from "../router";
import { useFetch } from "../useFetch";
import { ByChat, CoachMark } from "./uxFlow";
import { EmptyState, FetchError, InfoCallout, PageIntro } from "./ux";
import { agentColumns, deniedOf, readAgentSpecs } from "./agents/model";
import { AgentCounts } from "./agentsSlide/AgentCounts";
import { OrgChart } from "./agentsSlide/OrgChart";
import { SelectedAgentDetails } from "./agentsSlide/SelectedAgentDetails";
import { useAgentsData } from "./agentsSlide/useAgentsData";

export function useAgentDeckCols(): DeckCol[] {
  const hierarchy = useFetch(() => api.getConfig("hierarchy"), []);
  const pool = useFetch(() => api.getConfig("ephemeral_runtimes"), []);
  return useMemo(() => {
    if (deniedOf(hierarchy.data) || deniedOf(pool.data)) return [];
    return agentColumns(readAgentSpecs(hierarchy.data, pool.data));
  }, [hierarchy.data, pool.data]);
}

export function AgentsSlide() {
  const d = useAgentsData();

  return (
    <section className="panel ag-slide">
      <PageIntro
        title="Agents"
        lead="A structured view of the durable org and the worker profiles it can convene."
        howToggle
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
            <button type="button" className="btn" onClick={d.refresh}>
              Refresh
            </button>
          </>
        }
      />

      <CoachMark id="boltrig.coach.agents-org">
        Each card is an agent profile. Select one to see live facts, or open it
        for the full slide.
      </CoachMark>

      {d.loading && <p className="muted">Loading the org...</p>}
      <FetchError error={d.hierarchy.error} status={d.hierarchy.errorStatus} onRetry={d.hierarchy.reload} />
      {!d.hierarchy.error && (
        <FetchError error={d.pool.error} status={d.pool.errorStatus} onRetry={d.pool.reload} />
      )}

      {d.denied && !d.loading && (
        <InfoCallout tone="warn" title="No access to the agent org">
          The server declined this read ({d.denied}). Ask an admin to widen your
          access.
        </InfoCallout>
      )}

      {d.empty && (
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

      {!d.denied && d.agents.length > 0 && (
        <>
          <AgentCounts
            chief={d.chief}
            headsCount={d.heads.length}
            workersCount={d.workers.length}
            verbCount={d.caps.data?.verbs?.length}
          />
          <OrgChart
            chief={d.chief}
            heads={d.heads}
            workers={d.workers}
            selectedAgent={d.selectedAgent}
            onSelect={d.setSelected}
          />
          <SelectedAgentDetails agent={d.selectedAgent} />
        </>
      )}
    </section>
  );
}
