import { api } from "@/api/client";
import { csvToList, errText, parseJson } from "@/panels/shared";
import type { EvalFields } from "./useEvalFields";

export interface EvalActions {
  createCase: () => Promise<void>;
  run: () => Promise<void>;
}

export function useEvalActions(f: EvalFields): EvalActions {
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
    f.setCreateBusy(true);
    f.setCreateError(null);
    f.setCreateMsg(null);
    try {
      const res = await api.createEvalCase({
        id: f.caseId.trim() || undefined,
        target_kind: f.targetKind,
        target_ref: f.targetRef.trim(),
        input: parsedInput,
        assertions: parsedAssertions,
        labels: csvToList(f.labels),
      });
      if (res.status === "ok") {
        f.setCreateMsg(`Created case ${res.id}. It's selected below - run it next.`);
        if (res.id) f.setRunId(res.id);
        f.runs.reload();
      } else {
        f.setCreateError(`${res.status}: ${res.reason ?? "rejected"}`);
      }
    } catch (err) {
      f.setCreateError(errText(err));
    } finally {
      f.setCreateBusy(false);
    }
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

  return { createCase, run };
}
