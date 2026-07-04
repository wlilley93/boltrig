import { useEvalFields, type EvalFields } from "./useEvalFields";
import { useEvalDerived, type EvalDerived } from "./useEvalDerived";
import { useEvalActions, type EvalActions } from "./useEvalActions";

export type EvalState = EvalFields & EvalDerived & EvalActions;

export function useEvalState(): EvalState {
  const fields = useEvalFields();
  const derived = useEvalDerived(fields);
  const actions = useEvalActions(fields);
  return { ...fields, ...derived, ...actions };
}
