import { useInsightFields, type InsightFields } from "./useInsightFields";
import { useInsightActions, type InsightActions } from "./useInsightActions";

export type InsightState = InsightFields & InsightActions;

export function useInsightState(): InsightState {
  const fields = useInsightFields();
  const actions = useInsightActions(fields);
  return { ...fields, ...actions };
}
