import { useMemo, useState } from "react";

import { api } from "@/api/client";
import type {
  CapabilitiesResponse,
  ConfigSectionResponse,
} from "@/api/types";
import { useFetch, type FetchState } from "@/useFetch";
import {
  deniedOf,
  enrichAgents,
  mergeCapabilityProfiles,
  readAgentSpecs,
  type AgentModel,
} from "@/panels/agents/model";

export interface AgentsData {
  hierarchy: FetchState<ConfigSectionResponse>;
  pool: FetchState<ConfigSectionResponse>;
  caps: FetchState<CapabilitiesResponse>;
  denied: string | null;
  loading: boolean;
  empty: boolean;
  agents: AgentModel[];
  chief: AgentModel | undefined;
  heads: AgentModel[];
  workers: AgentModel[];
  selectedAgent: AgentModel | undefined;
  selected: string | null;
  setSelected: (v: string | null) => void;
  refresh: () => void;
}

export function useAgentsData(): AgentsData {
  const hierarchy = useFetch(() => api.getConfig("hierarchy"), []);
  const pool = useFetch(() => api.getConfig("ephemeral_runtimes"), []);
  const skills = useFetch(() => api.skills(), []);
  const caps = useFetch(() => api.capabilities(), []);
  const budgets = useFetch(() => api.budgets(), [], 30000);
  const work = useFetch(() => api.work(), [], 30000);
  const [selected, setSelected] = useState<string | null>(null);

  const denied = deniedOf(hierarchy.data) ?? deniedOf(pool.data);
  const specs = useMemo(
    () => mergeCapabilityProfiles(
      readAgentSpecs(hierarchy.data, pool.data),
      caps.data?.agent_capabilities ?? [],
    ),
    [hierarchy.data, pool.data, caps.data?.agent_capabilities],
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

  const loading = (hierarchy.loading && !hierarchy.data) || (pool.loading && !pool.data);
  const empty = !loading && !denied && agents.length === 0;

  function refresh() {
    hierarchy.reload();
    pool.reload();
    skills.reload();
    caps.reload();
  }

  return {
    hierarchy, pool, caps, denied, loading, empty, agents, chief, heads,
    workers, selectedAgent, selected, setSelected, refresh,
  };
}
