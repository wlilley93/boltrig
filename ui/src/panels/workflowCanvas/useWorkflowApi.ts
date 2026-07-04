import type { Edge } from "@xyflow/react";
import type { FetchState } from "@/useFetch";
import { api } from "@/api/client";
import type {
  StatusAck,
  VerbInfo,
  WorkflowRunRecord,
  WorkflowSourceValue,
  WorkflowSummary,
  WorkflowsResponse,
} from "@/api/types";
import { csvToList, errText, listToCsv } from "@/panels/shared";
import { extractSteps, graphToSteps, stepsToGraph } from "./graph";
import type { CanvasNode } from "./types";

interface Meta {
  wfId: string;
  setWfId: (v: string) => void;
  version: string;
  setVersion: (v: string) => void;
  source: WorkflowSourceValue;
  setSource: (v: WorkflowSourceValue) => void;
  tags: string;
  setTags: (v: string) => void;
  setSaveBusy: (v: boolean) => void;
  setSaveError: (v: string | null) => void;
  setAck: (v: StatusAck | null) => void;
  setRunBusy: (v: boolean) => void;
  setRunError: (v: string | null) => void;
  setRunResult: (v: WorkflowRunRecord | null) => void;
  setRunView: (v: { runId: string; wfId: string } | null) => void;
  viewRunId: string;
}

interface Graph {
  nodes: CanvasNode[];
  edges: Edge[];
  setNodes: import("react").Dispatch<import("react").SetStateAction<CanvasNode[]>>;
  setEdges: import("react").Dispatch<import("react").SetStateAction<Edge[]>>;
  setSelectedId: (id: string | null) => void;
  setLoadError: (v: string | null) => void;
}

interface ApiProps {
  meta: Meta;
  graph: Graph;
  verbsById: Map<string, VerbInfo>;
  workflows: FetchState<WorkflowsResponse>;
}

export function useWorkflowApi({
  meta,
  graph,
  verbsById,
  workflows,
}: ApiProps) {
  return {
    pickWorkflow: (w: WorkflowSummary) =>
      void pickWorkflow(w, meta, graph, verbsById),
    save: () => void saveWorkflow(meta, graph, workflows),
    run: () => void runWorkflow(meta),
    openRunCanvas: () => openRunCanvas(meta),
  };
}

async function pickWorkflow(
  w: WorkflowSummary,
  meta: Meta,
  graph: Graph,
  verbsById: Map<string, VerbInfo>,
) {
  meta.setWfId(w.id);
  meta.setVersion(w.version || "1.0.0");
  meta.setSource((w.source as WorkflowSourceValue) || "precreated");
  meta.setTags(listToCsv(w.intent_tags));
  graph.setLoadError(null);
  try {
    const detail = await api.getWorkflow(w.id);
    const steps = extractSteps(detail.definition) ?? [];
    const g = stepsToGraph(steps, verbsById);
    graph.setNodes(g.nodes);
    graph.setEdges(g.edges);
    graph.setSelectedId(null);
  } catch (err) {
    graph.setLoadError(`load '${w.id}': ${errText(err)}`);
  }
}

async function saveWorkflow(
  meta: Meta,
  graph: Graph,
  workflows: FetchState<WorkflowsResponse>,
) {
  const id = meta.wfId.trim();
  if (!id) {
    meta.setSaveError("Workflow id is required.");
    return;
  }
  meta.setSaveBusy(true);
  meta.setSaveError(null);
  meta.setAck(null);
  try {
    const steps = graphToSteps(graph.nodes, graph.edges);
    const res = await api.upsertWorkflow({
      id,
      version: meta.version.trim() || "1.0.0",
      source: meta.source,
      definition: { steps },
      intent_tags: csvToList(meta.tags),
    });
    meta.setAck(res);
    if (res.status === "ok") workflows.reload();
  } catch (err) {
    meta.setSaveError(errText(err));
  } finally {
    meta.setSaveBusy(false);
  }
}

async function runWorkflow(meta: Meta) {
  const id = meta.wfId.trim();
  if (!id) {
    meta.setRunError("Workflow id is required.");
    return;
  }
  meta.setRunBusy(true);
  meta.setRunError(null);
  meta.setRunResult(null);
  try {
    const record = await api.executeWorkflow(id, {});
    meta.setRunResult(record);
    if (record.run_id) meta.setRunView({ runId: record.run_id, wfId: id });
  } catch (err) {
    meta.setRunError(errText(err));
  } finally {
    meta.setRunBusy(false);
  }
}

function openRunCanvas(meta: Meta) {
  const id = meta.wfId.trim();
  const rid = meta.viewRunId.trim();
  if (!id || !rid) {
    meta.setRunError("Workflow id and run id are required to view a run.");
    return;
  }
  meta.setRunError(null);
  meta.setRunView({ runId: rid, wfId: id });
}
