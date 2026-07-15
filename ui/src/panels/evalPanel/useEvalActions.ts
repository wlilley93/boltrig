import { api } from "@/api/client";
import { csvToList, errText, parseJson } from "@/panels/shared";
import {
  outputRecord,
  useControlMutation,
  type ControlMutationState,
} from "@/panels/uxFlow/useControlMutation";
import type { EvalFields } from "./useEvalFields";

export interface EvalActions {
  createCase: () => Promise<void>;
  run: () => Promise<void>;
  createMutation: ControlMutationState;
}

export function useEvalActions(f: EvalFields): EvalActions {
  const createMutation = useControlMutation({
    verb: "control.eval_case.upsert",
    onApplied(output) {
      const created = outputRecord(output);
      const id = typeof created.id === "string" ? created.id : "";
      f.setCreateMsg(`Created case ${id || "successfully"}. It's selected below - run it next.`);
      if (id) f.setRunId(id);
      f.cases.reload();
    },
  });

  async function createCase() {
    if (!f.targetRef.trim()) {
      f.setCreateError("Pick a skill or workflow to test first.");
      return;
    }
    let parsedInput: Record<string, unknown>;
    let parsedAssertions: Record<string, unknown>;
    try {
      parsedInput = parseJson<Record<string, unknown>>(f.input, {});
      parsedAssertions = parseJson<Record<string, unknown>>(f.assertions, {});
    } catch (err) {
      f.setCreateError(errText(err));
      return;
    }
    f.setCreateError(null);
    f.setCreateMsg(null);
    const params: Record<string, unknown> = {
      target_kind: f.targetKind,
      target_ref: f.targetRef.trim(),
      input: parsedInput,
      assertions: parsedAssertions,
      labels: csvToList(f.labels),
    };
    if (f.caseId.trim()) params.id = f.caseId.trim();
    await createMutation.invoke(params);
  }

  async function run() {
    if (!f.runId.trim()) {
      f.setRunError("Pick a case to run first.");
      return;
    }
    f.setRunBusy(true);
    f.setRunError(null);
    f.setRunResult(null);
    try {
      const res = await api.runEval({ case_id: f.runId.trim() });
      if (res.error) f.setRunError(res.error);
      else {
        f.setRunResult(res);
        f.runs.reload();
      }
    } catch (err) {
      f.setRunError(errText(err));
    } finally {
      f.setRunBusy(false);
    }
  }

  return { createCase, run, createMutation };
}
