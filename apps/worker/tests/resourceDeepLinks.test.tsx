// @vitest-environment happy-dom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  agentCapabilities: vi.fn(),
  auditTree: vi.fn(),
  capabilities: vi.fn(),
  capabilityChangelog: vi.fn(),
  channels: vi.fn(),
  evalCases: vi.fn(),
  evalRuns: vi.fn(),
  hitl: vi.fn(),
  knowledgeAsset: vi.fn(),
  knowledgeAssets: vi.fn(),
  knowledgeProviders: vi.fn(),
  memoryFact: vi.fn(),
  memoryFacts: vi.fn(),
  modelEndpoints: vi.fn(),
  permanentFleet: vi.fn(),
  runs: vi.fn(),
  runTopology: vi.fn(),
  work: vi.fn(),
  workDetail: vi.fn(),
  workflow: vi.fn(),
  workflowRuns: vi.fn(),
  workflowStats: vi.fn(),
  workflowScheduleOccurrences: vi.fn(),
  workflows: vi.fn(),
  workflowTriggerFinalizations: vi.fn(),
  workflowTriggers: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { AutomationsView } from "../src/components/AutomationView";
import { EvaluationsView } from "../src/components/EvaluationsView";
import {
  AgentsView,
  KnowledgeView,
  MemoryView,
  RunsView,
  WorkView,
} from "../src/components/ParityViews";

beforeEach(() => {
  api.workflowScheduleOccurrences.mockImplementation(async (id: string) => ({
    workflow_id: id,
    occurrences: [],
    truncated: false,
    backfill: {
      status: "unavailable",
      reason: "historical_backfill_not_supported_by_canonical_claim",
    },
  }));
  api.auditTree.mockResolvedValue({ root: null });
  api.capabilities.mockResolvedValue({ verbs: [] });
  api.channels.mockResolvedValue({ channels: [] });
  api.evalRuns.mockResolvedValue({ runs: [] });
  api.capabilityChangelog.mockResolvedValue({ changes: [] });
  api.hitl.mockResolvedValue({ requests: [] });
  api.knowledgeProviders.mockResolvedValue({ providers: [] });
  api.modelEndpoints.mockResolvedValue({ endpoints: [] });
  api.permanentFleet.mockResolvedValue({
    status: "not_configured",
    hierarchy: null,
    generation: null,
    revision: null,
    apply_state: "not_configured",
    observations: [],
  });
  api.runTopology.mockResolvedValue({ root: null });
  api.workflowRuns.mockResolvedValue({ workflow_id: "", runs: [] });
  api.workflowStats.mockResolvedValue({ stats: [] });
  api.workflowTriggerFinalizations.mockResolvedValue({
    workflow_id: "",
    finalizations: [],
  });
  api.workflowTriggers.mockResolvedValue({ workflow_id: "", triggers: [] });
});

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
  window.location.hash = "";
});

describe("Worker durable resource links", () => {
  it("restores a selected run inspector", async () => {
    window.location.hash = "#/runs/run-deep";
    api.runs.mockResolvedValue({
      runs: [{
        run_id: "run-deep",
        work_item: "work-deep",
        intent: "Deep run",
        status: "done",
      }],
      next_cursor: null,
    });

    render(<RunsView />);

    await waitFor(() => expect(api.auditTree).toHaveBeenCalledWith("run-deep"));
    expect(screen.getByLabelText("Run details")).toBeTruthy();
  });

  it("loads work detail directly instead of depending on the list page", async () => {
    window.location.hash = "#/work/work%2Fdeep";
    api.work.mockResolvedValue({ items: [], next_cursor: null });
    api.workDetail.mockResolvedValue({
      item: { id: "work/deep", intent: "Deep work", status: "pending" },
      children: [],
      audit: [],
    });

    render(<WorkView />);

    await waitFor(() => expect(api.workDetail).toHaveBeenCalledWith("work/deep"));
    expect(screen.getByLabelText("Work item details")).toBeTruthy();
  });

  it("opens the selected governed agent profile", async () => {
    window.location.hash = "#/agents/codex-researcher";
    api.agentCapabilities.mockResolvedValue({
      agent_capabilities: [{
        name: "codex-researcher",
        runtime: "codex",
        supported_skills: ["research"],
        max_depth: 2,
        is_ephemeral: false,
        cost_tier: "standard",
        model_endpoint: null,
        familiar_genotype: { source: "agent_capability.name.v1", palette: [] },
        source: "control-plane",
        is_active: true,
        status: "active",
      }],
    });

    render(<AgentsView />);

    expect(await screen.findByRole("heading", { name: "Edit codex-researcher" })).toBeTruthy();
  });

  it("hydrates selected knowledge provenance by asset id", async () => {
    window.location.hash = "#/knowledge/asset-deep";
    const asset = {
      id: "asset-deep",
      title: "Deep source",
      filename: "deep.pdf",
      segment_count: 1,
      revision_id: "revision-deep",
      source_kind: "upload",
      source_ref: null,
    };
    api.knowledgeAssets.mockResolvedValue({ assets: [asset], next_offset: null });
    api.knowledgeAsset.mockResolvedValue({
      asset,
      segments: [],
      projections: [],
      provenance: { source_kind: "upload" },
    });

    render(<KnowledgeView />);

    await waitFor(() => expect(api.knowledgeAsset).toHaveBeenCalledWith("asset-deep"));
    expect(screen.getByLabelText("Close source detail")).toBeTruthy();
  });

  it("hydrates an exact memory fact outside the browse page", async () => {
    window.location.hash = "#/memory/fact%2Fdeep";
    api.memoryFacts.mockResolvedValue({
      facts: [],
      scopes: ["user:alice"],
    });
    api.memoryFact.mockResolvedValue({
      fact: {
        id: "fact/deep",
        owner_scope: "user:alice",
        kind: "decision",
        content: "Renew annually",
        data_class: "standard",
        provenance: {
          source_kind: "conversation",
          source_ref: "conversation/deep",
        },
      },
    });

    render(<MemoryView />);

    await waitFor(() => expect(api.memoryFact).toHaveBeenCalledWith("fact/deep"));
    expect(await screen.findByLabelText("Memory fact details")).toBeTruthy();
    expect(screen.getByText("Renew annually")).toBeTruthy();
  });

  it("opens a workflow editor from an automation link", async () => {
    window.location.hash = "#/automations/daily%2Freview";
    const workflow = {
      id: "daily/review",
      version: "1.0.0",
      source: "precreated",
      intent_tags: [],
      status: "active",
      definition: { steps: [] },
    };
    api.workflows.mockResolvedValue({ workflows: [workflow] });
    api.workflow.mockResolvedValue(workflow);

    render(<AutomationsView />);

    await waitFor(() => expect(api.workflow).toHaveBeenCalledWith("daily/review"));
    expect(await screen.findByLabelText("Workflow id")).toBeTruthy();
  });

  it("restores a selected evaluation case and its history scope", async () => {
    window.location.hash = "#/evaluations/safe-triage";
    api.evalCases.mockResolvedValue({
      cases: [{
        id: "safe-triage",
        target_kind: "skill",
        target_ref: "triage",
        input: {},
        assertions: {},
        labels: [],
        is_active: true,
        status: "active",
      }],
    });

    render(<EvaluationsView />);

    expect(await screen.findByLabelText("safe-triage evaluation")).toBeTruthy();
  });
});
