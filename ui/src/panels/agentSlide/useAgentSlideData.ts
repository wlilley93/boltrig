import { useMemo } from "react";

import { api } from "../../api/client";
import type { BudgetItem, SkillSummary, VerbInfo, WorkItem } from "../../api/types";
import { useFetch } from "../../useFetch";
import {
  deniedOf,
  enrichAgents,
  readAgentSpecs,
  readModelEndpoints,
  runtimeOptions,
  type AgentModel,
} from "../agents/model";
import { buildSkillOptions } from "./types";

export interface AgentSlideData {
  agent: AgentModel | undefined;
  denied: string | null;
  loading: boolean;
  modelEndpoints: ReturnType<typeof readModelEndpoints>;
  runtimes: string[];
  skillOptions: ReturnType<typeof buildSkillOptions>;
  skillsList: SkillSummary[];
  verbsList: VerbInfo[];
  budgetsList: BudgetItem[];
  workList: WorkItem[];
  skillsError: string | null;
  skillsErrorStatus: number | null;
  skillsReload: () => void;
  capsError: string | null;
  capsErrorStatus: number | null;
  capsReload: () => void;
}

export function useAgentSlideData(agentName: string): AgentSlideData {
  const hierarchy = useFetch(() => api.getConfig("hierarchy"), []);
  const pool = useFetch(() => api.getConfig("ephemeral_runtimes"), []);
  const models = useFetch(() => api.getConfig("models"), []);
  const skills = useFetch(() => api.skills(), []);
  const caps = useFetch(() => api.capabilities(), []);
  const budgets = useFetch(() => api.budgets(), [], 30000);
  const work = useFetch(() => api.work(), [], 30000);

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
  const agent = agents.find((a) => a.name === agentName);
  const modelEndpoints = useMemo(() => readModelEndpoints(models.data), [models.data]);
  const runtimes = useMemo(() => runtimeOptions(specs), [specs]);
  const skillOptions = useMemo(
    () => buildSkillOptions(skills.data?.skills ?? []),
    [skills.data],
  );
  const loading = (hierarchy.loading && !hierarchy.data) || (pool.loading && !pool.data);

  return {
    agent,
    denied,
    loading,
    modelEndpoints,
    runtimes,
    skillOptions,
    skillsList: skills.data?.skills ?? [],
    verbsList: caps.data?.verbs ?? [],
    budgetsList: budgets.data?.budgets ?? [],
    workList: work.data?.items ?? [],
    skillsError: skills.error,
    skillsErrorStatus: skills.errorStatus,
    skillsReload: skills.reload,
    capsError: caps.error,
    capsErrorStatus: caps.errorStatus,
    capsReload: caps.reload,
  };
}
