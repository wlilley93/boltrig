import { useAgentSlideData, type AgentSlideData } from "./useAgentSlideData";
import { useAgentSlideForm, type AgentSlideForm } from "./useAgentSlideForm";

export type AgentSlideState = AgentSlideData & AgentSlideForm;

export function useAgentSlide(agentName: string): AgentSlideState {
  const data = useAgentSlideData(agentName);
  const form = useAgentSlideForm({
    agent: data.agent,
    skills: data.skillsList,
    verbs: data.verbsList,
    budgets: data.budgetsList,
    work: data.workList,
  });
  return { ...data, ...form };
}
