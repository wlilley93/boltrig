import { useState } from "react";

import { api } from "@/api/client";
import type {
  CapabilitiesResponse,
  EvalCasesResponse,
  EvalRunResult,
  EvalRunsResponse,
  SkillsResponse,
  WorkflowsResponse,
} from "@/api/types";
import { useFetch, type FetchState } from "@/useFetch";

export interface EvalFields {
  caseId: string;
  setCaseId: (v: string) => void;
  targetKind: "skill" | "workflow";
  setTargetKind: (v: "skill" | "workflow") => void;
  targetRef: string;
  setTargetRef: (v: string) => void;
  input: string;
  setInput: (v: string) => void;
  assertions: string;
  setAssertions: (v: string) => void;
  labels: string;
  setLabels: (v: string) => void;
  createBusy: boolean;
  setCreateBusy: (v: boolean) => void;
  createError: string | null;
  setCreateError: (v: string | null) => void;
  createMsg: string | null;
  setCreateMsg: (v: string | null) => void;
  runId: string;
  setRunId: (v: string) => void;
  runBusy: boolean;
  setRunBusy: (v: boolean) => void;
  runError: string | null;
  setRunError: (v: string | null) => void;
  runResult: EvalRunResult | null;
  setRunResult: (v: EvalRunResult | null) => void;
  filterCase: string;
  setFilterCase: (v: string) => void;
  cases: FetchState<EvalCasesResponse>;
  runs: FetchState<EvalRunsResponse>;
  skills: FetchState<SkillsResponse>;
  workflows: FetchState<WorkflowsResponse>;
  caps: FetchState<CapabilitiesResponse>;
}

export function useEvalFields(): EvalFields {
  const [caseId, setCaseId] = useState("");
  const [targetKind, setTargetKind] = useState<"skill" | "workflow">("skill");
  const [targetRef, setTargetRef] = useState("");
  const [input, setInput] = useState("{}");
  const [assertions, setAssertions] = useState(
    '{"forbidden_grants": ["ticket.create"]}',
  );
  const [labels, setLabels] = useState("");
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [createMsg, setCreateMsg] = useState<string | null>(null);
  const [runId, setRunId] = useState("");
  const [runBusy, setRunBusy] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [runResult, setRunResult] = useState<EvalRunResult | null>(null);
  const [filterCase, setFilterCase] = useState("");

  const cases = useFetch(() => api.evalCases(), []);
  const runs = useFetch(
    () => api.evalRuns(filterCase.trim() || undefined),
    [filterCase],
  );
  const skills = useFetch(() => api.skills(), []);
  const workflows = useFetch(() => api.workflows(), []);
  const caps = useFetch(() => api.capabilities(), []);

  return {
    caseId, setCaseId, targetKind, setTargetKind, targetRef, setTargetRef,
    input, setInput, assertions, setAssertions, labels, setLabels, createBusy,
    setCreateBusy, createError, setCreateError, createMsg, setCreateMsg, runId,
    setRunId, runBusy, setRunBusy, runError, setRunError, runResult,
    setRunResult, filterCase, setFilterCase, cases, runs, skills, workflows, caps,
  };
}
