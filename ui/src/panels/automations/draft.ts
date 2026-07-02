import { useEffect, useState } from "react";

export interface WorkflowDraftStep {
  id: string;
  parents: string[];
  action: string;
  params?: Record<string, unknown>;
  description?: string;
}

const drafts = new Map<string, WorkflowDraftStep[]>();
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

export function getWorkflowDraft(wfid: string | undefined): WorkflowDraftStep[] | undefined {
  return wfid ? drafts.get(wfid) : undefined;
}

export function setWorkflowDraft(wfid: string, steps: WorkflowDraftStep[]) {
  drafts.set(wfid, steps.map((step) => ({ ...step, parents: [...step.parents] })));
  emit();
}

export function clearWorkflowDraft(wfid: string) {
  drafts.delete(wfid);
  emit();
}

export function useWorkflowDraft(wfid: string | undefined): WorkflowDraftStep[] | undefined {
  const [, setVersion] = useState(0);
  useEffect(() => {
    const listener = () => setVersion((v) => v + 1);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);
  return getWorkflowDraft(wfid);
}
