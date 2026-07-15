import { useMemo } from "react";

import type { EvalCaseItem, EvalRunSummary, VerbInfo } from "@/api/types";
import { parseJson } from "@/panels/shared";
import type { EvalFields } from "./useEvalFields";

export interface Option {
  value: string;
  label: string;
}

export interface EvalDerived {
  targetOptions: Option[];
  verbs: VerbInfo[];
  forbidden: string[];
  toggleForbidden: (verbId: string) => void;
  changeTargetKind: (v: string) => void;
  caseIdOptions: Option[];
  savedCases: EvalCaseItem[];
  runList: EvalRunSummary[];
}

export function useEvalDerived(f: EvalFields): EvalDerived {
  const verbs = f.caps.data?.verbs ?? [];

  const targetOptions = useMemo(() => {
    const ids =
      f.targetKind === "skill"
        ? (f.skills.data?.skills ?? []).map((s) => s.id)
        : (f.workflows.data?.workflows ?? []).map((w) => w.id);
    return [
      { value: "", label: `Choose a ${f.targetKind}...` },
      ...ids.map((id) => ({ value: id, label: id })),
    ];
  }, [f.targetKind, f.skills.data, f.workflows.data]);

  // The forbidden-grants set is derived from (and written back to) the assertions
  // JSON, so the guided chips and the raw JSON never disagree.
  const forbidden = useMemo(() => {
    try {
      const o = parseJson<{ forbidden_grants?: unknown }>(f.assertions, {});
      return Array.isArray(o.forbidden_grants)
        ? (o.forbidden_grants as string[])
        : [];
    } catch {
      return [];
    }
  }, [f.assertions]);

  function toggleForbidden(verbId: string) {
    if (!verbId) return;
    let o: Record<string, unknown>;
    try {
      o = parseJson<Record<string, unknown>>(f.assertions, {});
    } catch {
      o = {};
    }
    const list = Array.isArray(o.forbidden_grants)
      ? (o.forbidden_grants as string[])
      : [];
    const next = list.includes(verbId)
      ? list.filter((x) => x !== verbId)
      : [...list, verbId];
    f.setAssertions(JSON.stringify({ ...o, forbidden_grants: next }, null, 2));
  }

  function changeTargetKind(v: string) {
    f.setTargetKind(v === "workflow" ? "workflow" : "skill");
    f.setTargetRef("");
  }

  const caseIdOptions = useMemo(() => {
    const labels = new Map<string, string>();
    for (const c of f.cases.data?.cases ?? []) {
      labels.set(c.id, `${c.id} - ${c.target_kind}:${c.target_ref}`);
    }
    for (const r of f.runs.data?.runs ?? []) {
      if (r.case_id && !labels.has(r.case_id)) labels.set(r.case_id, r.case_id);
    }
    if (f.runId && !labels.has(f.runId)) labels.set(f.runId, f.runId);
    return [
      { value: "", label: "Choose a case..." },
      ...[...labels].map(([value, label]) => ({ value, label })),
    ];
  }, [f.cases.data, f.runs.data, f.runId]);

  const savedCases: EvalCaseItem[] = f.cases.data?.cases ?? [];
  const runList: EvalRunSummary[] = f.runs.data?.runs ?? [];

  return {
    targetOptions, verbs, forbidden, toggleForbidden, changeTargetKind,
    caseIdOptions, savedCases, runList,
  };
}
