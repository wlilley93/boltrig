import { useState } from "react";
import type {
  StatusAck,
  WorkflowRunRecord,
  WorkflowSourceValue,
} from "@/api/types";

export function useWorkflowMeta(routeWfId?: string) {
  const [wfId, setWfId] = useState(routeWfId ?? "");
  const [version, setVersion] = useState("1.0.0");
  const [source, setSource] = useState<WorkflowSourceValue>("precreated");
  const [tags, setTags] = useState("");
  const [saveBusy, setSaveBusy] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [ack, setAck] = useState<StatusAck | null>(null);
  const [runBusy, setRunBusy] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [runResult, setRunResult] = useState<WorkflowRunRecord | null>(null);
  const [runView, setRunView] = useState<{ runId: string; wfId: string } | null>(
    null,
  );
  const [viewRunId, setViewRunId] = useState("");
  return {
    wfId,
    setWfId,
    version,
    setVersion,
    source,
    setSource,
    tags,
    setTags,
    saveBusy,
    setSaveBusy,
    saveError,
    setSaveError,
    ack,
    setAck,
    runBusy,
    setRunBusy,
    runError,
    setRunError,
    runResult,
    setRunResult,
    runView,
    setRunView,
    viewRunId,
    setViewRunId,
  };
}
