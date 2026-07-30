// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  archiveWorkflow: vi.fn(),
  addons: vi.fn(),
  agentCapabilities: vi.fn(),
  capabilities: vi.fn(),
  auditTree: vi.fn(),
  assignWork: vi.fn(),
  channels: vi.fn(),
  createWorkflowTrigger: vi.fn(),
  createWork: vi.fn(),
  disableWorkflowTrigger: vi.fn(),
  disconnectIntegration: vi.fn(),
  executeWorkflow: vi.fn(),
  integrationCatalogue: vi.fn(),
  integrationConnections: vi.fn(),
  invokeApprovalState: vi.fn(),
  knowledgeAsset: vi.fn(),
  knowledgeAssets: vi.fn(),
  knowledgeProviders: vi.fn(),
  eraseKnowledgeAsset: vi.fn(),
  setKnowledgeProvider: vi.fn(),
  memoryFacts: vi.fn(),
  memoryFact: vi.fn(),
  memoryForget: vi.fn(),
  memoryImprove: vi.fn(),
  memoryIngest: vi.fn(),
  memoryIngestions: vi.fn(),
  memoryRecall: vi.fn(),
  memoryRemember: vi.fn(),
  modelEndpoints: vi.fn(),
  permanentFleet: vi.fn(),
  applyPermanentFleet: vi.fn(),
  runs: vi.fn(),
  runTopology: vi.fn(),
  scheduleWorkflow: vi.fn(),
  restoreWorkflow: vi.fn(),
  retryWorkflowScheduleOccurrence: vi.fn(),
  reparentWork: vi.fn(),
  restoreAgentCapability: vi.fn(),
  retireAgentCapability: vi.fn(),
  startIntegrationOAuth: vi.fn(),
  submitIntegrationSecret: vi.fn(),
  triggerWorkflow: vi.fn(),
  transitionWork: vi.fn(),
  unscheduleWorkflow: vi.fn(),
  upsertWorkflow: vi.fn(),
  workflow: vi.fn(),
  workflowTriggerDeliveries: vi.fn(),
  workflowTriggerFinalizations: vi.fn(),
  workflowTriggers: vi.fn(),
  workflowRuns: vi.fn(),
  workflowScheduleOccurrences: vi.fn(),
  workflowStats: vi.fn(),
  workflows: vi.fn(),
  work: vi.fn(),
  workDetail: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { AutomationsView } from "../src/components/AutomationView";
import { IntegrationsView } from "../src/components/IntegrationsView";
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
  api.workflowTriggerFinalizations.mockResolvedValue({
    workflow_id: "",
    finalizations: [],
  });
  api.modelEndpoints.mockResolvedValue({ endpoints: [] });
  api.permanentFleet.mockResolvedValue({
    status: "not_configured",
    hierarchy: null,
    generation: null,
    revision: null,
    apply_state: "not_configured",
    observations: [],
  });
});

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
  window.location.hash = "";
});

describe("Worker bounded history pagination", () => {
  it("loads the next scoped run page with the opaque server cursor", async () => {
    api.runs
      .mockResolvedValueOnce({
        runs: [{ run_id: "run-a", work_item: "work-a", intent: "First", status: "done" }],
        next_cursor: "cursor/run-a",
      })
      .mockResolvedValueOnce({
        runs: [{ run_id: "run-b", work_item: "work-b", intent: "Second", status: "done" }],
        next_cursor: null,
      });

    render(<RunsView />);
    await screen.findByText("First");
    fireEvent.click(screen.getByRole("button", { name: "Load more runs" }));
    await screen.findByText("Second");
    expect(api.runs).toHaveBeenLastCalledWith({ cursor: "cursor/run-a" });
  });

  it("loads the next scoped work page without replacing the current page", async () => {
    api.work
      .mockResolvedValueOnce({
        items: [{ id: "work-a", intent: "First work", status: "pending" }],
        next_cursor: "cursor/work-a",
      })
      .mockResolvedValueOnce({
        items: [{ id: "work-b", intent: "Second work", status: "pending" }],
        next_cursor: null,
      });

    render(<WorkView />);
    await screen.findByText("First work");
    fireEvent.click(screen.getByRole("button", { name: "Load more work" }));
    await screen.findByText("Second work");
    expect(screen.getByText("First work")).toBeTruthy();
    expect(api.work).toHaveBeenLastCalledWith(undefined, { cursor: "cursor/work-a" });
  });
});

describe("Worker governed Work lifecycle", () => {
  it("creates canonical work without implying source-system writeback", async () => {
    api.work.mockResolvedValue({ items: [], next_cursor: null });
    api.createWork.mockResolvedValue({
      status: "ok",
      item: {
        id: "work-new",
        intent: "Prepare launch",
        status: "pending",
        owner_member: "engineering",
        source: "internal",
      },
    });
    api.workDetail.mockResolvedValue({
      item: {
        id: "work-new",
        intent: "Prepare launch",
        status: "pending",
        owner_member: "engineering",
        source: "internal",
      },
      children: [],
      audit: [],
    });

    render(<WorkView />);
    fireEvent.change(screen.getByLabelText("New work intent"), {
      target: { value: "Prepare launch" },
    });
    fireEvent.change(screen.getByLabelText("New work owner"), {
      target: { value: "engineering" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(api.createWork).toHaveBeenCalledWith(expect.objectContaining({
      intent: "Prepare launch",
      owner_member: "engineering",
      parent_id: null,
    })));
    expect(await screen.findByText(/No source-system writeback was attempted/)).toBeTruthy();
  });

  it("keeps a pending assignment honest in the Work detail controls", async () => {
    const item = {
      id: "work-a",
      intent: "Root task",
      status: "pending",
      owner_member: "engineering",
      source: "internal",
    };
    api.work.mockResolvedValue({ items: [item], next_cursor: null });
    api.workDetail.mockResolvedValue({ item, children: [], audit: [] });
    api.assignWork.mockResolvedValue({
      status: "pending_human",
      hitl_request_id: "hitl-work",
    });

    render(<WorkView />);
    fireEvent.click(await screen.findByRole("button", { name: /Root task/ }));
    fireEvent.change(await screen.findByLabelText("Owner"), {
      target: { value: "operations" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Assign" }));

    await waitFor(() => expect(api.assignWork).toHaveBeenCalledWith(
      "work-a", "operations", expect.any(String),
    ));
    expect(await screen.findByText(/waiting for approval in Inbox/)).toBeTruthy();
  });

  it("replays the exact approved Work status transition", async () => {
    const item = {
      id: "work-a",
      intent: "Root task",
      status: "pending",
      owner_member: "engineering",
      source: "internal",
    };
    api.work.mockResolvedValue({ items: [item], next_cursor: null });
    api.workDetail.mockResolvedValue({ item, children: [], audit: [] });
    api.transitionWork
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval-work-status",
      })
      .mockResolvedValueOnce({
        status: "ok",
        item: { ...item, status: "blocked" },
      });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });

    render(<WorkView />);
    fireEvent.click(await screen.findByRole("button", { name: /Root task/ }));
    fireEvent.change(await screen.findByLabelText("Status"), {
      target: { value: "blocked" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Change status" }));
    fireEvent.click(await screen.findByRole("button", {
      name: "Check approval and apply exact change",
    }));

    await waitFor(() => expect(api.transitionWork).toHaveBeenLastCalledWith(
      "work-a",
      "blocked",
      expect.any(String),
      "approval-work-status",
    ));
  });
});

describe("Worker memory feedback", () => {
  it("reweights a visible fact through the scoped memory improve route", async () => {
    api.memoryFacts.mockResolvedValue({
      scopes: ["user:alice"],
      facts: [{
        id: "fact-a",
        owner_scope: "user:alice",
        kind: "decision",
        content: "Renew annually",
        data_class: "standard",
        provenance: { source_kind: "conversation", source_ref: "conversation-a" },
      }],
    });
    api.memoryImprove.mockResolvedValue({ status: "ok", adjusted: 1 });

    render(<MemoryView />);
    fireEvent.click(await screen.findByRole("button", { name: "Useful" }));

    await waitFor(() => expect(api.memoryImprove).toHaveBeenCalledWith({
      target: "fact-a",
      signal: "up",
    }));
    expect(await screen.findByText(/Marked as useful/)).toBeTruthy();
  });
});

describe("Worker Memory approval continuation", () => {
  it("replays one exact approved batch ingestion through the same route", async () => {
    api.memoryFacts.mockResolvedValue({
      scopes: ["user:alice"],
      facts: [],
    });
    api.memoryIngestions.mockResolvedValue({ ingestions: [] });
    api.memoryIngest
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval-memory-ingest",
      })
      .mockResolvedValueOnce({
        status: "ok",
        id: "ingestion-a",
        ingestion_status: "done",
        facts_added: 1,
        screened: true,
      });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });

    render(<MemoryView />);
    fireEvent.click(await screen.findByRole("button", { name: "Ingest" }));
    fireEvent.change(screen.getByLabelText("Source reference"), {
      target: { value: "source-a" },
    });
    fireEvent.change(screen.getByLabelText("Candidate facts (one per line)"), {
      target: { value: "Approved fact" },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Ingest" }).at(-1)!);
    fireEvent.click(await screen.findByRole("button", {
      name: "Check approval and apply exact change",
    }));

    await waitFor(() => expect(api.memoryIngest).toHaveBeenLastCalledWith(
      {
        source_kind: "conversation",
        source_ref: "source-a",
        owner_scope: "user:alice",
        items: ["Approved fact"],
      },
      "approval-memory-ingest",
    ));
    expect(await screen.findByText(/Ingestion ingestion-a added 1 facts/)).toBeTruthy();
  });

  it("invalidates a pending ingestion when its component-held input changes", async () => {
    api.memoryFacts.mockResolvedValue({
      scopes: ["user:alice"],
      facts: [],
    });
    api.memoryIngestions.mockResolvedValue({ ingestions: [] });
    api.memoryIngest.mockResolvedValue({
      status: "pending_human",
      hitl_request_id: "approval-memory-ingest",
    });

    render(<MemoryView />);
    fireEvent.click(await screen.findByRole("button", { name: "Ingest" }));
    fireEvent.change(screen.getByLabelText("Source reference"), {
      target: { value: "source-a" },
    });
    fireEvent.change(screen.getByLabelText("Candidate facts (one per line)"), {
      target: { value: "Original fact" },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Ingest" }).at(-1)!);
    await screen.findByText(/Memory ingestion is waiting for approval/);

    fireEvent.change(screen.getByLabelText("Candidate facts (one per line)"), {
      target: { value: "Changed fact" },
    });

    expect(await screen.findByText(/Memory ingestion changed/)).toBeTruthy();
    expect(screen.queryByRole("button", {
      name: "Check approval and apply exact change",
    })).toBeNull();
    expect(api.memoryIngest).toHaveBeenCalledTimes(1);
  });
});

describe("Worker Knowledge approval continuation", () => {
  it("does not offer enablement for an unimplemented provider", async () => {
    api.knowledgeAssets.mockResolvedValue({
      assets: [],
      next_offset: null,
    });
    api.knowledgeProviders.mockResolvedValue({
      providers: [{
        id: "supermemory",
        display_name: "Supermemory",
        role: "managed_context",
        enabled: false,
        bundled: false,
        health: "unavailable",
        status: "unavailable",
        last_error: "Credential-backed projection adapter is not implemented in this build.",
      }],
    });

    render(<KnowledgeView />);
    fireEvent.click(await screen.findByRole("button", { name: "Providers" }));

    expect(
      (await screen.findByRole("button", { name: "Unavailable" })).hasAttribute("disabled"),
    ).toBe(true);
    expect(api.setKnowledgeProvider).not.toHaveBeenCalled();
  });

  it("replays only the exact approved provider change", async () => {
    api.knowledgeAssets.mockResolvedValue({
      assets: [],
      next_offset: null,
    });
    api.knowledgeProviders.mockResolvedValue({
      providers: [{
        id: "cognee",
        display_name: "Cognee",
        role: "graph",
        enabled: false,
        bundled: true,
        health: "unknown",
        status: "available",
      }],
    });
    api.setKnowledgeProvider
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval-provider",
      })
      .mockResolvedValueOnce({
        status: "ok",
        provider: {
          id: "cognee",
          display_name: "Cognee",
          role: "graph",
          enabled: true,
          bundled: true,
          health: "unknown",
          status: "enabled",
        },
      });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });

    render(<KnowledgeView />);
    fireEvent.click(await screen.findByRole("button", { name: "Providers" }));
    fireEvent.click(screen.getByRole("button", { name: "Enable" }));
    fireEvent.click(await screen.findByRole("button", {
      name: "Check approval and apply exact change",
    }));

    await waitFor(() => expect(api.setKnowledgeProvider).toHaveBeenLastCalledWith(
      "cognee",
      true,
      "approval-provider",
    ));
    expect(await screen.findByText("Provider enabled.")).toBeTruthy();
  });

  it("replays only the exact approved source erasure", async () => {
    api.knowledgeAssets.mockResolvedValue({
      assets: [{
        id: "asset-a",
        title: "Source A",
        filename: "source-a.txt",
        asset_type: "text",
        revision_id: "revision-a",
        source_kind: "upload",
        segment_count: 1,
        created_at: "2026-01-01T00:00:00Z",
      }],
      next_offset: null,
    });
    api.knowledgeProviders.mockResolvedValue({ providers: [] });
    api.eraseKnowledgeAsset
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval-erase",
      })
      .mockResolvedValueOnce({
        status: "ok",
        asset_id: "asset-a",
        operation_status: "erased",
      });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });

    render(<KnowledgeView />);
    fireEvent.click(await screen.findByRole("button", { name: "Erase" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm erase" }));
    fireEvent.click(await screen.findByRole("button", {
      name: "Check approval and apply exact change",
    }));

    await waitFor(() => expect(api.eraseKnowledgeAsset).toHaveBeenLastCalledWith(
      "asset-a",
      "approval-erase",
    ));
    expect(await screen.findByText("The source was erased.")).toBeTruthy();
  });
});

describe("Worker native automation authoring", () => {
  function mockAutomationDetail(
    detail: Record<string, unknown>,
    triggers: Record<string, unknown>[] = [],
    channels: Record<string, unknown>[] = [],
  ) {
    api.workflows.mockResolvedValue({ workflows: [detail] });
    api.capabilities.mockResolvedValue({ verbs: [] });
    api.workflowStats.mockResolvedValue({ stats: [] });
    api.workflowRuns.mockImplementation(async (id: string) => ({
      workflow_id: id,
      runs: [],
    }));
    api.workflowTriggers.mockImplementation(async (id: string) => ({
      workflow_id: id,
      triggers,
    }));
    api.channels.mockResolvedValue({ channels });
    api.workflow.mockResolvedValue(detail);
  }

  it("authors a dependency step through the canonical workflow upsert", async () => {
    api.workflows.mockResolvedValue({ workflows: [] });
    api.capabilities.mockResolvedValue({
      verbs: [{ id: "work.create", noun: "work", consequence: "high" }],
    });
    api.upsertWorkflow.mockResolvedValue({ status: "ok", id: "daily-review" });

    render(<AutomationsView />);
    await waitFor(() => expect(api.capabilities).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "New workflow" }));
    fireEvent.change(screen.getByLabelText("Workflow id"), {
      target: { value: "daily-review" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add step" }));

    expect(screen.getByLabelText("Step id")).toBeTruthy();
    expect((screen.getByLabelText("Governed action") as HTMLInputElement).value).toBe("work.create");
    expect(screen.getByLabelText("Depends on")).toBeTruthy();
    expect(screen.getByLabelText("Parameters (JSON object)")).toBeTruthy();
    expect(screen.queryByRole("combobox", { name: "Source" })).toBeNull();
    expect(screen.getByText("Assigned by Boltrig")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.upsertWorkflow).toHaveBeenCalledWith({
      id: "daily-review",
      version: "1.0.0",
      intent_tags: [],
      definition: {
        steps: [{
          id: "step-1",
          action: "work.create",
          parents: [],
        }],
      },
    }));
  });

  it("invalidates edited workflow approval and replays only the exact approved save", async () => {
    const saved = {
      id: "approval-workflow",
      version: "2.0.0",
      source: "generated",
      intent_tags: [],
      definition: { steps: [] },
      status: "active",
      schedule: null,
    };
    api.workflows
      .mockResolvedValueOnce({ workflows: [] })
      .mockResolvedValue({ workflows: [saved] });
    api.capabilities.mockResolvedValue({ verbs: [] });
    api.workflowStats.mockResolvedValue({ stats: [] });
    api.workflow.mockResolvedValue(saved);
    api.workflowRuns.mockResolvedValue({
      workflow_id: saved.id,
      runs: [],
    });
    api.workflowTriggers.mockResolvedValue({
      workflow_id: saved.id,
      triggers: [],
    });
    api.channels.mockResolvedValue({ channels: [] });
    api.upsertWorkflow
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval-save-old",
      })
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval-save-exact",
      })
      .mockResolvedValueOnce({ status: "ok", id: "approval-workflow" });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });

    render(<AutomationsView />);
    fireEvent.click(await screen.findByRole("button", { name: "New workflow" }));
    fireEvent.change(screen.getByLabelText("Workflow id"), {
      target: { value: "approval-workflow" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText("Workflow save is waiting for approval"),
    ).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Version"), {
      target: { value: "2.0.0" },
    });
    expect(await screen.findByText("Workflow save changed")).toBeTruthy();
    expect(api.invokeApprovalState).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    fireEvent.click(await screen.findByRole("button", {
      name: "Check approval and apply exact change",
    }));

    await waitFor(() => expect(api.invokeApprovalState).toHaveBeenCalledWith(
      "approval-save-exact",
    ));
    await waitFor(() => expect(api.upsertWorkflow).toHaveBeenLastCalledWith({
      id: "approval-workflow",
      version: "2.0.0",
      intent_tags: [],
      definition: { steps: [] },
    }, "approval-save-exact"));
    await waitFor(() => expect(screen.queryByText(
      "Workflow save is waiting for approval",
    )).toBeNull());
  });

  it("replays exact approved schedule and lifecycle route inputs", async () => {
    const base = {
      id: "governed-schedule",
      version: "1.0.0",
      source: "precreated",
      intent_tags: [],
      definition: { steps: [] },
      status: "active",
      schedule: {
        type: "cron",
        cron: "0 9 * * *",
        timezone: "UTC",
      },
    };
    mockAutomationDetail(base);
    api.scheduleWorkflow
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval-schedule",
      })
      .mockResolvedValueOnce({
        status: "ok",
        id: base.id,
        schedule: base.schedule,
      });
    api.unscheduleWorkflow
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval-unschedule",
      })
      .mockResolvedValueOnce({
        status: "ok",
        id: base.id,
        schedule: null,
      });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });

    render(<AutomationsView />);
    fireEvent.click(await screen.findByRole("button", { name: /governed-schedule/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Save schedule" }));
    fireEvent.click(await screen.findByRole("button", {
      name: "Check approval and apply exact change",
    }));
    await waitFor(() => expect(api.scheduleWorkflow).toHaveBeenLastCalledWith(
      base.id,
      { cron: "0 9 * * *", timezone: "UTC" },
      "approval-schedule",
    ));

    fireEvent.click(await screen.findByRole("button", { name: "Unschedule" }));
    fireEvent.click(await screen.findByRole("button", {
      name: "Check approval and apply exact change",
    }));
    await waitFor(() => expect(api.unscheduleWorkflow).toHaveBeenLastCalledWith(
      base.id, "approval-unschedule",
    ));
  });

  it("replays approved queue and execute requests without inventing a second run path", async () => {
    const base = {
      id: "governed-run",
      version: "1.0.0",
      source: "precreated",
      intent_tags: [],
      definition: { steps: [] },
      status: "active",
      schedule: null,
    };
    mockAutomationDetail(base);
    api.triggerWorkflow
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval-queue",
      })
      .mockResolvedValueOnce({
        run_id: "run-queued",
        status: "queued",
        engine: "hatchet",
      });
    api.executeWorkflow
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval-execute",
      })
      .mockResolvedValueOnce({
        run_id: "run-executed",
        workflow_id: base.id,
        version: "1.0.0",
        status: "completed",
        steps: [],
        inputs: {},
      });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });

    render(<AutomationsView />);
    fireEvent.click(await screen.findByRole("button", { name: /governed-run/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Queue run" }));
    fireEvent.click(await screen.findByRole("button", {
      name: "Check approval and apply exact change",
    }));
    await waitFor(() => expect(api.triggerWorkflow).toHaveBeenLastCalledWith(
      base.id, { inputs: {} }, "approval-queue",
    ));
    expect(await screen.findByText(/Run run-queued queued on hatchet/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Run now" }));
    fireEvent.click(await screen.findByRole("button", {
      name: "Check approval and apply exact change",
    }));
    await waitFor(() => expect(api.executeWorkflow).toHaveBeenLastCalledWith(
      base.id, {}, "approval-execute",
    ));
    expect(await screen.findByText("Run run-executed completed.")).toBeTruthy();
  });

  it("renders schedule desired/observed truth and explains required authority", async () => {
    const state = {
      desired: {
        status: "active",
        cron: "0 9 * * 1-5",
        timezone: "UTC",
      },
      observed: {
        status: "needs_action",
        reason: "scheduling_authority_not_bound",
        next_run_at: null,
        last_scheduled_for: null,
        observed_at: null,
      },
    };
    const base = {
      id: "scheduled-review",
      version: "1.0.0",
      source: "precreated",
      intent_tags: [],
      definition: { steps: [] },
      status: "active",
      schedule: {
        type: "cron",
        cron: "0 9 * * 1-5",
        timezone: "UTC",
      },
      schedule_state: state,
    };
    api.workflows.mockResolvedValue({ workflows: [base] });
    api.capabilities.mockResolvedValue({ verbs: [] });
    api.workflowStats.mockResolvedValue({ stats: [] });
    api.workflowRuns.mockResolvedValue({ workflow_id: base.id, runs: [] });
    api.workflowTriggers.mockResolvedValue({
      workflow_id: base.id,
      triggers: [],
    });
    api.channels.mockResolvedValue({ channels: [] });
    api.workflow.mockResolvedValue(base);
    api.scheduleWorkflow.mockResolvedValue({
      status: "ok",
      id: base.id,
      schedule: base.schedule,
      schedule_state: state,
    });

    render(<AutomationsView />);
    expect(await screen.findByText(/scheduler needs action/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /scheduled-review/i }));
    expect(await screen.findByText(/Observed: needs action/)).toBeTruthy();
    expect(screen.getByText(/bind a current human scheduling authority/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Save schedule" }));
    await waitFor(() => expect(api.scheduleWorkflow).toHaveBeenCalledWith(
      base.id,
      { cron: "0 9 * * 1-5", timezone: "UTC" },
    ));
    expect(await screen.findByText(
      /Schedule desired state saved, but action is required/,
    )).toBeTruthy();
  });

  it("continues only the exact approved failed schedule occurrence", async () => {
    const base = {
      id: "scheduled-recovery",
      version: "1.0.0",
      source: "precreated",
      intent_tags: [],
      definition: { steps: [] },
      status: "active",
      schedule: {
        type: "cron",
        cron: "0 9 * * *",
        timezone: "UTC",
      },
    };
    const occurrence = {
      scheduled_for: "2026-07-29T09:00:00+00:00",
      run_id: "wfs_exact",
      status: "failed",
      claimed_at: "2026-07-29T09:00:00+00:00",
      enqueued_at: null,
      outcome_at: "2026-07-29T09:00:01+00:00",
      engine_outcome: {
        status: "settled",
        recovery: "not_applicable",
      },
      reason: "schedule_dispatch_failed",
      retry: {
        attempts: 3,
        manual_retries: 0,
        last_retry_at: null,
      },
    };
    api.workflows.mockResolvedValue({ workflows: [base] });
    api.capabilities.mockResolvedValue({ verbs: [] });
    api.workflowStats.mockResolvedValue({ stats: [] });
    api.workflowRuns.mockResolvedValue({ workflow_id: base.id, runs: [] });
    api.workflowTriggers.mockResolvedValue({
      workflow_id: base.id,
      triggers: [],
    });
    api.channels.mockResolvedValue({ channels: [] });
    api.workflow.mockResolvedValue(base);
    api.workflowScheduleOccurrences.mockResolvedValue({
      workflow_id: base.id,
      occurrences: [occurrence],
      truncated: false,
      backfill: {
        status: "unavailable",
        reason: "historical_backfill_not_supported_by_canonical_claim",
      },
    });
    api.retryWorkflowScheduleOccurrence
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval-occurrence-old",
      })
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval-occurrence",
      })
      .mockResolvedValueOnce({
        status: "ok",
        workflow_id: base.id,
        scheduled_for: occurrence.scheduled_for,
        run_id: occurrence.run_id,
        occurrence_status: "retryable",
        manual_retries: 1,
      });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });

    render(<AutomationsView />);
    fireEvent.click(
      await screen.findByRole("button", { name: /scheduled-recovery/i }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Retry same run" }),
    );
    expect(
      await screen.findByText("Waiting for an Inbox decision"),
    ).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Cron expression"), {
      target: { value: "0 10 * * *" },
    });
    expect(
      await screen.findByText("Pending occurrence retry changed"),
    ).toBeTruthy();
    expect(api.invokeApprovalState).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Retry same run" }));
    expect(
      await screen.findByText("Waiting for an Inbox decision"),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and continue exact retry",
    }));

    await waitFor(() => expect(api.invokeApprovalState).toHaveBeenCalledWith(
      "approval-occurrence",
    ));
    await waitFor(() => expect(
      api.retryWorkflowScheduleOccurrence,
    ).toHaveBeenLastCalledWith(
      base.id,
      occurrence.scheduled_for,
      occurrence.run_id,
      "approval-occurrence",
    ));
    expect(
      await screen.findByText(/exact approved occurrence was queued/i),
    ).toBeTruthy();
  });

  it("unschedules, archives, and restores through governed lifecycle routes", async () => {
    const base = {
      id: "daily-review",
      version: "1.0.0",
      source: "precreated",
      intent_tags: [],
      definition: { steps: [] },
    };
    api.workflows.mockResolvedValue({
      workflows: [{ ...base, status: "active", schedule: {
        type: "cron", cron: "0 9 * * 1-5", timezone: "UTC",
      } }],
    });
    api.capabilities.mockResolvedValue({ verbs: [] });
    api.workflowStats.mockResolvedValue({ stats: [] });
    api.workflowRuns.mockResolvedValue({ workflow_id: base.id, runs: [] });
    api.workflowTriggers.mockResolvedValue({
      workflow_id: base.id,
      triggers: [],
    });
    api.channels.mockResolvedValue({ channels: [] });
    api.workflow
      .mockResolvedValueOnce({
        ...base,
        status: "active",
        schedule: { type: "cron", cron: "0 9 * * 1-5", timezone: "UTC" },
      })
      .mockResolvedValueOnce({ ...base, status: "active", schedule: null })
      .mockResolvedValueOnce({ ...base, status: "archived", schedule: null })
      .mockResolvedValueOnce({ ...base, status: "active", schedule: null });
    api.unscheduleWorkflow.mockResolvedValue({ status: "ok", schedule: null });
    api.archiveWorkflow.mockResolvedValue({
      status: "ok", workflow_status: "archived", schedule: null,
    });
    api.restoreWorkflow.mockResolvedValue({
      status: "ok", workflow_status: "active", schedule: null,
    });

    render(<AutomationsView />);
    fireEvent.click(await screen.findByRole("button", { name: /daily-review/i }));
    fireEvent.click(await screen.findByRole("button", { name: "Unschedule" }));
    await waitFor(() => expect(api.unscheduleWorkflow).toHaveBeenCalledWith(base.id));

    fireEvent.click(await screen.findByRole("button", { name: "Archive workflow" }));
    await waitFor(() => expect(api.archiveWorkflow).toHaveBeenCalledWith(base.id));
    expect(await screen.findByRole("button", { name: "Restore workflow" })).toBeTruthy();
    expect((screen.getByRole("button", { name: "Queue run" }) as HTMLButtonElement).disabled)
      .toBe(true);
    expect((screen.getByRole("button", { name: "Run now" }) as HTMLButtonElement).disabled)
      .toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Restore workflow" }));
    await waitFor(() => expect(api.restoreWorkflow).toHaveBeenCalledWith(base.id));
    expect(await screen.findByRole("button", { name: "Archive workflow" })).toBeTruthy();
  });

  it("binds a webhook and renders its one-time material without list recovery", async () => {
    const base = {
      id: "event-review",
      version: "1.0.0",
      source: "precreated",
      intent_tags: [],
      definition: { steps: [] },
      status: "active",
    };
    api.workflows.mockResolvedValue({ workflows: [base] });
    api.capabilities.mockResolvedValue({ verbs: [] });
    api.workflowStats.mockResolvedValue({ stats: [] });
    api.workflowRuns.mockResolvedValue({ workflow_id: base.id, runs: [] });
    api.workflow.mockResolvedValue(base);
    api.workflowTriggers.mockResolvedValue({
      workflow_id: base.id,
      triggers: [],
    });
    api.channels.mockResolvedValue({ channels: [] });
    api.createWorkflowTrigger
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "hitl-webhook-binding",
      })
      .mockResolvedValueOnce({
        status: "ok",
        trigger_id: "trigger-a",
        workflow_id: base.id,
        source: "webhook",
        enabled: true,
        secret: "wft_show-once",
        webhook_path: "/v1/automation-hooks/acme/trigger-a",
      });

    const firstMount = render(<AutomationsView />);
    fireEvent.click(await screen.findByRole("button", { name: /event-review/i }));
    fireEvent.change(await screen.findByLabelText("Trigger binding name"), {
      target: { value: "provider events" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Bind source" }));

    await waitFor(() => expect(api.createWorkflowTrigger).toHaveBeenCalledWith(
      base.id,
      { name: "provider events", source: "webhook" },
    ));
    expect(await screen.findByText(/Finalize the approved webhook binding/)).toBeTruthy();
    expect(
      (screen.getByRole("button", {
        name: "Finalize after approval",
      }) as HTMLButtonElement).disabled,
    ).toBe(true);

    firstMount.unmount();
    api.workflowTriggerFinalizations.mockResolvedValue({
      workflow_id: base.id,
      finalizations: [{
        request_id: "hitl-webhook-binding",
        action: "create",
        state: "ready",
        name: "provider events",
        source: "webhook",
      }],
    });
    render(<AutomationsView />);
    fireEvent.click(await screen.findByRole("button", { name: /event-review/i }));
    await screen.findByText(/Finalize the approved webhook binding/);
    fireEvent.click(screen.getByRole("button", { name: "Finalize after approval" }));
    await waitFor(() => expect(api.createWorkflowTrigger).toHaveBeenLastCalledWith(
      base.id,
      { name: "provider events", source: "webhook" },
      "hitl-webhook-binding",
    ));
    expect(await screen.findByText("wft_show-once")).toBeTruthy();
    expect(screen.getByText("/v1/automation-hooks/acme/trigger-a")).toBeTruthy();
    expect(screen.getByText(/retains only the secret digest/)).toBeTruthy();
  });

  it("shows immutable trigger delivery state and governs disabling", async () => {
    const base = {
      id: "channel-review",
      version: "1.0.0",
      source: "precreated",
      intent_tags: [],
      definition: { steps: [] },
      status: "active",
    };
    const trigger = {
      id: "trigger-channel",
      workflow_id: base.id,
      workspace_id: null,
      name: "verified provider",
      source: "channel",
      owner_id: "author",
      channel_id: "events",
      enabled: true,
      secret_configured: false,
      created_at: null,
      updated_at: null,
    };
    api.workflows.mockResolvedValue({ workflows: [base] });
    api.capabilities.mockResolvedValue({ verbs: [] });
    api.workflowStats.mockResolvedValue({ stats: [] });
    api.workflowRuns.mockResolvedValue({ workflow_id: base.id, runs: [] });
    api.workflow.mockResolvedValue(base);
    api.workflowTriggers.mockResolvedValue({
      workflow_id: base.id,
      triggers: [trigger],
    });
    api.channels.mockResolvedValue({ channels: [] });
    api.workflowTriggerDeliveries.mockResolvedValue({
      workflow_id: base.id,
      trigger_id: trigger.id,
      deliveries: [{
        trigger_id: trigger.id,
        event_digest: "d".repeat(64),
        status: "pending_human",
        authority_subject: "verified-sender",
        run_id: null,
        hitl_request_id: "hitl-a",
        reason: null,
        created_at: null,
      }],
    });
    api.disableWorkflowTrigger
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "hitl-disable",
      })
      .mockResolvedValueOnce({
        status: "ok",
        trigger_id: trigger.id,
        workflow_id: base.id,
        enabled: false,
      });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });

    render(<AutomationsView />);
    fireEvent.click(await screen.findByRole("button", { name: /channel-review/i }));
    fireEvent.click(await screen.findByRole("button", { name: "Delivery history" }));
    expect(await screen.findByText("verified-sender")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Disable" }));
    await waitFor(() => expect(api.disableWorkflowTrigger).toHaveBeenCalledWith(
      base.id, trigger.id,
    ));
    expect(await screen.findByText(/Disable is waiting for approval/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));
    await waitFor(() => expect(api.disableWorkflowTrigger).toHaveBeenLastCalledWith(
      base.id, trigger.id, "hitl-disable",
    ));
    expect(await screen.findByText("Trigger disabled.")).toBeTruthy();
  });

  it("binds only an explicitly selected enabled channel and renders pending", async () => {
    const base = {
      id: "provider-intake",
      version: "1.0.0",
      source: "precreated",
      intent_tags: [],
      definition: { steps: [] },
      status: "active",
    };
    api.workflows.mockResolvedValue({ workflows: [base] });
    api.capabilities.mockResolvedValue({ verbs: [] });
    api.workflowStats.mockResolvedValue({ stats: [] });
    api.workflowRuns.mockResolvedValue({ workflow_id: base.id, runs: [] });
    api.workflow.mockResolvedValue(base);
    api.workflowTriggers.mockResolvedValue({
      workflow_id: base.id,
      triggers: [],
    });
    api.channels.mockResolvedValue({
      channels: [
        {
          id: "enabled-events",
          name: "Events",
          platform: "webhook",
          transport: "webhook",
          enabled: true,
          unpaired_behavior: "deny",
          config: {},
          credential_configured: true,
        },
        {
          id: "disabled-events",
          name: "Disabled",
          platform: "webhook",
          transport: "webhook",
          enabled: false,
          unpaired_behavior: "deny",
          config: {},
          credential_configured: true,
        },
      ],
    });
    api.createWorkflowTrigger
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "hitl-channel-binding",
      })
      .mockResolvedValueOnce({
        status: "ok",
        trigger_id: "trigger-channel",
        workflow_id: base.id,
        source: "channel",
        enabled: true,
      });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });

    render(<AutomationsView />);
    fireEvent.click(await screen.findByRole("button", { name: /provider-intake/i }));
    fireEvent.change(await screen.findByLabelText("Trigger binding name"), {
      target: { value: "provider channel" },
    });
    fireEvent.change(screen.getByLabelText("Trigger source"), {
      target: { value: "channel" },
    });
    const select = await screen.findByLabelText("Trigger channel");
    expect(screen.queryByRole("option", { name: /Disabled/ })).toBeNull();
    fireEvent.change(select, { target: { value: "enabled-events" } });
    fireEvent.click(screen.getByRole("button", { name: "Bind source" }));

    await waitFor(() => expect(api.createWorkflowTrigger).toHaveBeenCalledWith(
      base.id,
      {
        name: "provider channel",
        source: "channel",
        channel_id: "enabled-events",
      },
    ));
    expect(await screen.findByText(/Trigger binding is waiting for approval/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));
    await waitFor(() => expect(api.createWorkflowTrigger).toHaveBeenLastCalledWith(
      base.id,
      {
        name: "provider channel",
        source: "channel",
        channel_id: "enabled-events",
      },
      "hitl-channel-binding",
    ));
    expect(await screen.findByText("Event source bound to this workflow.")).toBeTruthy();
  });
});

describe("Worker Familiar identity", () => {
  it("renders startup evidence without claiming the worker is currently live", async () => {
    api.agentCapabilities.mockResolvedValue({ agent_capabilities: [] });
    api.permanentFleet.mockResolvedValue({
      status: "configured",
      hierarchy: {
        chief: {
          name: "chief-of-staff",
          routing_id: "cos",
          purpose: "Stored chief purpose",
          brief: "",
          runtime: "codex",
          model_endpoint: null,
          supported_skills: ["*"],
          max_depth: 3,
          cost_tier: "standard",
          budget: null,
        },
        departments: [{
          name: "research-head",
          routing_id: "research",
          purpose: "Stored research purpose",
          brief: "Stored, inactive brief",
          runtime: "codex",
          model_endpoint: null,
          supported_skills: ["research"],
          max_depth: 3,
          cost_tier: "standard",
          budget: null,
        }],
      },
      generation: "pf_0123456789abcdef01234567",
      revision: 1,
      apply_state: "startup_applied_liveness_unknown",
      profiles_reconciled: true,
      observations: [],
    });

    render(<AgentsView />);
    expect(await screen.findByText("startup applied · liveness unknown")).toBeTruthy();
    expect(screen.getByText(/current worker liveness is unknown/)).toBeTruthy();
    expect(screen.queryByText("observed applied")).toBeNull();
  });

  it("submits topology edits as restart-required desired state", async () => {
    api.agentCapabilities.mockResolvedValue({ agent_capabilities: [] });
    api.permanentFleet.mockResolvedValue({
      status: "configured",
      hierarchy: {
        chief: {
          name: "chief-of-staff",
          routing_id: "cos",
          purpose: "Coordinate work",
          brief: "",
          runtime: "codex",
          model_endpoint: null,
          supported_skills: ["*"],
          max_depth: 3,
          cost_tier: "standard",
          budget: null,
        },
        departments: [{
          name: "research-head",
          routing_id: "research",
          purpose: "Own research",
          brief: "",
          runtime: "script",
          model_endpoint: null,
          supported_skills: ["research"],
          max_depth: 3,
          cost_tier: "cheap",
          budget: null,
        }],
      },
      generation: "pf_0123456789abcdef01234567",
      revision: 1,
      apply_state: "restart_required",
      profiles_reconciled: false,
      observations: [],
    });
    api.applyPermanentFleet.mockResolvedValue({
      status: "ok",
      apply_state: "restart_required",
      hot_applied: false,
      profiles_reconciled: false,
      reconcile_at: "next_manifest_apply_or_redeploy",
    });

    render(<AgentsView />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit topology" }));
    fireEvent.change(screen.getAllByLabelText("Purpose")[1], {
      target: { value: "Own research and synthesis" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Request hierarchy change" }));

    await waitFor(() => expect(api.applyPermanentFleet).toHaveBeenCalled());
    expect(api.applyPermanentFleet.mock.calls[0][0].departments[0].purpose)
      .toBe("Own research and synthesis");
    expect(await screen.findByText(/No running worker was mutated/)).toBeTruthy();
  });

  it("renders the server-derived capability genotype without inventing a palette", async () => {
    api.agentCapabilities.mockResolvedValue({
      agent_capabilities: [{
        name: "researcher",
        runtime: "codex",
        supported_skills: ["research/*"],
        max_depth: 2,
        is_ephemeral: true,
        cost_tier: "cheap",
        model_endpoint: null,
        source: "control-plane",
        is_active: true,
        status: "active",
        familiar_genotype: {
          source: "agent_capability.name.v1",
          seed: 898153330,
          body: "kepler",
          palette: ["#ffedd5", "#f97316", "#7c2d12"],
          markings: ["orbit"],
          accessories: ["antenna"],
          voice_id: null,
        },
      }],
    });

    render(<AgentsView />);
    const familiar = await screen.findByRole("img", {
      name: "researcher profile Familiar",
    });
    expect(familiar.dataset.genotypeSource).toBe("agent_capability.name.v1");
    expect(familiar.getAttribute("style")).toContain("#ffedd5");
    expect(familiar.getAttribute("style")).toContain("#7c2d12");
  });

  it("keeps retired profiles visible and restores them through the governed route", async () => {
    const retired = {
      name: "archivist",
      runtime: "codex",
      supported_skills: ["records/*"],
      max_depth: 1,
      is_ephemeral: false,
      cost_tier: "standard",
      model_endpoint: null,
      source: "manifest",
      is_active: false,
      status: "retired",
      familiar_genotype: { source: "agent_capability.name.v1" },
    };
    api.agentCapabilities.mockResolvedValue({ agent_capabilities: [retired] });
    api.restoreAgentCapability.mockResolvedValue({
      status: "pending_human",
      hitl_request_id: "hitl-restore",
    });

    render(<AgentsView />);
    expect(await screen.findByText("retired · standard")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Restore profile" }));
    await waitFor(() => expect(api.restoreAgentCapability).toHaveBeenCalledWith("archivist"));
    expect(await screen.findByText(/Restore is waiting for approval/)).toBeTruthy();
    expect(api.retireAgentCapability).not.toHaveBeenCalled();
  });

  it("replays only the exact approved profile lifecycle request", async () => {
    const retired = {
      name: "archivist",
      runtime: "codex",
      supported_skills: ["records/*"],
      max_depth: 1,
      is_ephemeral: false,
      cost_tier: "standard",
      model_endpoint: null,
      source: "manifest",
      is_active: false,
      status: "retired",
      familiar_genotype: { source: "agent_capability.name.v1" },
    };
    api.agentCapabilities.mockResolvedValue({ agent_capabilities: [retired] });
    api.restoreAgentCapability
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "hitl-restore",
      })
      .mockResolvedValueOnce({
        status: "ok",
        id: "archivist",
        capability_status: "active",
      });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });

    render(<AgentsView />);
    fireEvent.click(await screen.findByRole("button", { name: "Restore profile" }));
    fireEvent.click(await screen.findByRole("button", {
      name: "Check approval and apply exact change",
    }));

    await waitFor(() => expect(api.invokeApprovalState).toHaveBeenCalledWith(
      "hitl-restore",
    ));
    await waitFor(() => expect(api.restoreAgentCapability).toHaveBeenLastCalledWith(
      "archivist",
      "hitl-restore",
    ));
    expect(await screen.findByText("archivist restored.")).toBeTruthy();
  });

  it("calls non-ephemeral rows persistent profiles, never live durable agents", async () => {
    api.agentCapabilities.mockResolvedValue({
      agent_capabilities: [{
        name: "department-profile",
        runtime: "codex",
        supported_skills: ["records/*"],
        max_depth: 2,
        is_ephemeral: false,
        cost_tier: "standard",
        model_endpoint: null,
        source: "manifest",
        is_active: true,
        status: "active",
        familiar_genotype: { source: "agent_capability.name.v1" },
      }],
    });

    render(<AgentsView />);
    expect(await screen.findByText("Persistent profile")).toBeTruthy();
    expect(screen.queryByText("Durable agent")).toBeNull();
  });
});

describe("Worker integration honesty", () => {
  const ticketEntry = {
    id: "tickets",
    label: "Tickets",
    category: "work",
    transport: "rest",
    auth: ["manual_secret"],
    description: "Reviewed ticket connector.",
    certification: "certified",
    available: true,
    setup_supported: true,
    setup_contract: null,
    enabled_tools: [],
  };
  const ticketConnection = {
    id: "conn-1",
    integration_id: "tickets",
    label: "Tickets",
    health: "healthy",
    credential_ref_present: true,
    accounts: [{ id: "support", label: "Tickets", selected: true }],
    enabled_tools: ["tickets.read"],
    created_at: "2026-07-29T00:00:00Z",
  };

  it("labels the catalogue as preview and keeps setup disabled without kernel routes", async () => {
    api.integrationCatalogue.mockRejectedValue(new Error("not found"));
    api.integrationConnections.mockRejectedValue(new Error("not found"));

    render(<IntegrationsView />);
    expect(screen.getByLabelText("Search integrations")).toBeTruthy();
    await screen.findByText(/Connection management is not enabled/);
    expect(screen.getAllByRole("button", { name: /^Details / }).length).toBe(40);
    expect(screen.queryAllByRole("button", { name: /^Connect / })).toHaveLength(0);
    expect(api.startIntegrationOAuth).not.toHaveBeenCalled();
  });

  it("keeps reviewed preview entries when the authoritative catalogue is empty", async () => {
    api.integrationCatalogue.mockResolvedValue({ integrations: [] });
    api.integrationConnections.mockResolvedValue({ connections: [] });

    render(<IntegrationsView />);
    await waitFor(() => expect(api.integrationConnections).toHaveBeenCalled());
    expect(screen.getAllByRole("button", { name: /^Details / })).toHaveLength(40);
    expect(screen.queryAllByRole("button", { name: /^Connect / })).toHaveLength(0);
  });

  it("keeps OAuth browser return and provider exchange explicitly unavailable", async () => {
    api.integrationCatalogue.mockResolvedValue({
      integrations: [{
        id: "tickets",
        label: "Tickets",
        category: "work",
        transport: "rest",
        auth: ["oauth2"],
        description: "Reviewed ticket connector.",
        certification: "certified",
        available: true,
        setup_supported: true,
        setup_contract: null,
        enabled_tools: [],
      }],
    });
    api.integrationConnections.mockResolvedValue({ connections: [] });
    api.startIntegrationOAuth.mockResolvedValue({
      authorization_url: "https://provider.invalid/authorize",
      state_expires_at: "2030-01-01T00:05:00Z",
    });
    const before = window.location.href;

    render(<IntegrationsView />);
    fireEvent.click(await screen.findByRole("button", {
      name: "Connect Tickets",
    }));

    expect(await screen.findByText(
      /no reviewed web OAuth callback contract/i,
    )).toBeTruthy();
    expect(screen.getByText("browser callback unavailable")).toBeTruthy();
    expect(window.location.href).toBe(before);
  });

  it("renders only declared secret fields and clears them after sealed setup", async () => {
    api.integrationCatalogue.mockResolvedValue({
      integrations: [{
        id: "tickets",
        label: "Tickets",
        category: "work",
        transport: "rest",
        auth: ["manual_secret"],
        description: "Reviewed ticket connector.",
        certification: "certified",
        available: true,
        setup_supported: true,
        setup_contract: {
          kind: "manual_secret",
          version: "tickets_v1",
          fields: [
            {
              name: "token",
              label: "API token",
              input_kind: "token",
              secret: true,
              required: true,
              min_length: 12,
              max_length: 200,
            },
            {
              name: "account_id",
              label: "Account ID",
              input_kind: "text",
              secret: false,
              required: true,
              min_length: 1,
              max_length: 100,
            },
          ],
          enabled_tools: [],
        },
      }],
    });
    api.integrationConnections.mockResolvedValue({ connections: [] });
    api.submitIntegrationSecret.mockResolvedValue({
      status: "connected",
      connection: {
        id: "conn-1",
        integration_id: "tickets",
        label: "Tickets",
        health: "pending",
        credential_ref_present: true,
        accounts: [{ id: "support", label: "Tickets", selected: true }],
        enabled_tools: [],
        created_at: "2026-07-29T00:00:00Z",
      },
    });

    render(<IntegrationsView />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect Tickets" }));
    const form = screen.getByRole("form", { name: "Connect Tickets" });
    const token = within(form).getByLabelText("API token") as HTMLInputElement;
    const account = within(form).getByLabelText("Account ID") as HTMLInputElement;
    fireEvent.change(token, { target: { value: "write-only-token" } });
    fireEvent.change(account, { target: { value: "support" } });
    fireEvent.click(within(form).getByRole("button", { name: "Seal and connect" }));

    await waitFor(() => expect(api.submitIntegrationSecret).toHaveBeenCalledWith(
      "tickets",
      {
        label: "Tickets",
        fields: { token: "write-only-token", account_id: "support" },
      },
    ));
    expect(await screen.findByText(/submitted secret cannot be retrieved/)).toBeTruthy();
    expect(screen.queryByLabelText("API token")).toBeNull();
    expect(screen.queryByLabelText("Unknown field")).toBeNull();
  });

  it("replays the exact approved integration revocation without retaining a secret", async () => {
    api.integrationCatalogue.mockResolvedValue({ integrations: [ticketEntry] });
    api.integrationConnections
      .mockResolvedValueOnce({ connections: [ticketConnection] })
      .mockResolvedValue({ connections: [] });
    api.disconnectIntegration
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "hitl-revoke",
      })
      .mockResolvedValueOnce({ status: "revoked" });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });

    render(<IntegrationsView />);
    fireEvent.click(await screen.findByRole("button", { name: "Manage Tickets" }));
    fireEvent.click(await screen.findByRole("button", { name: "Disconnect" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm disconnect" }));
    fireEvent.click(await screen.findByRole("button", {
      name: "Check approval and apply exact change",
    }));

    await waitFor(() => expect(api.disconnectIntegration).toHaveBeenLastCalledWith(
      "conn-1",
      "hitl-revoke",
    ));
    expect(await screen.findByText("Tickets disconnected.")).toBeTruthy();
    expect(screen.queryByLabelText("Tickets connection")).toBeNull();
    expect(JSON.stringify(api.disconnectIntegration.mock.calls)).not.toContain("token");
  });

  it("invalidates a pending revocation when the requester closes its connection", async () => {
    api.integrationCatalogue.mockResolvedValue({ integrations: [ticketEntry] });
    api.integrationConnections.mockResolvedValue({
      connections: [ticketConnection],
    });
    api.disconnectIntegration.mockResolvedValue({
      status: "pending_human",
      hitl_request_id: "hitl-stale-revoke",
    });

    render(<IntegrationsView />);
    fireEvent.click(await screen.findByRole("button", { name: "Manage Tickets" }));
    fireEvent.click(await screen.findByRole("button", { name: "Disconnect" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm disconnect" }));
    await screen.findByRole("button", {
      name: "Check approval and apply exact change",
    });

    fireEvent.click(screen.getByRole("button", {
      name: "Close connection details",
    }));

    expect(await screen.findByText("Tickets disconnection changed")).toBeTruthy();
    expect(screen.queryByRole("button", {
      name: "Check approval and apply exact change",
    })).toBeNull();
    expect(api.invokeApprovalState).not.toHaveBeenCalled();
    expect(api.disconnectIntegration).toHaveBeenCalledTimes(1);
  });
});

describe("Worker runtime add-on inventory", () => {
  function connectionFallbacks() {
    api.integrationCatalogue.mockResolvedValue({ integrations: [] });
    api.integrationConnections.mockResolvedValue({ connections: [] });
  }

  it("keeps loading distinct from a canonical empty inventory", async () => {
    connectionFallbacks();
    api.addons.mockReturnValue(new Promise(() => undefined));

    const { unmount } = render(<IntegrationsView />);
    expect(screen.getByText("Checking the kernel add-on inventory…")).toBeTruthy();
    unmount();

    api.addons.mockResolvedValue({
      scope: { tenant_id: "tenant-a", workspace_id: "workspace-a" },
      addons: [],
    });
    render(<IntegrationsView />);
    expect(await screen.findByText("No runtime add-ons are installed in this build.")).toBeTruthy();
    expect(screen.queryByText("Add-on inventory unavailable.")).toBeNull();
  });

  it("renders inactive, ready, degraded, unavailable, and unverified as server states", async () => {
    connectionFallbacks();
    const base = {
      version: "1.0.0",
      installation: "installed",
      activation: "active",
      contributions: {
        harness: false,
        adapter: false,
        consequence_hint: false,
      },
      configuration: { status: "ready", requirements: [] },
    };
    api.addons.mockResolvedValue({
      scope: { tenant_id: "tenant-a", workspace_id: "workspace-a" },
      addons: [
        {
          ...base,
          id: "inactive-addon",
          activation: "inactive",
          runtime: { status: "inactive", reason: null },
        },
        {
          ...base,
          id: "ready-addon",
          contributions: {
            harness: true,
            adapter: true,
            consequence_hint: true,
          },
          runtime: { status: "ready", reason: null },
        },
        {
          ...base,
          id: "degraded-addon",
          configuration: { status: "degraded", requirements: [] },
          runtime: { status: "degraded", reason: "health_degraded" },
        },
        {
          ...base,
          id: "unavailable-addon",
          configuration: { status: "missing", requirements: [] },
          runtime: { status: "unavailable", reason: "record_missing" },
        },
        {
          ...base,
          id: "unverified-addon",
          configuration: { status: "unverified", requirements: [] },
          runtime: { status: "unverified", reason: "health_unverified" },
        },
      ],
    });

    render(<IntegrationsView />);

    expect(await screen.findByText("inactive-addon")).toBeTruthy();
    const region = screen.getByRole("region", { name: "Runtime add-ons" });
    expect(within(region).getByText("Installed / inactive")).toBeTruthy();
    expect(within(region).getByText("Ready")).toBeTruthy();
    expect(within(region).getByText("degraded")).toBeTruthy();
    expect(within(region).getByText("unavailable")).toBeTruthy();
    expect(within(region).getByText("unverified")).toBeTruthy();
    expect(within(region).getByText("Agent guidance")).toBeTruthy();
    expect(within(region).getByText("Adapter binding")).toBeTruthy();
    expect(within(region).getByText("Risk mapping")).toBeTruthy();
    expect(within(region).queryAllByRole("button")).toHaveLength(0);
  });

  it("keeps authorization denial distinct from API unavailability", async () => {
    connectionFallbacks();
    api.addons.mockRejectedValue({ status: 403 });

    const { unmount } = render(<IntegrationsView />);
    expect(await screen.findByText(/Add-on inventory denied/)).toBeTruthy();
    expect(screen.queryByText("Add-on inventory unavailable.")).toBeNull();
    unmount();

    api.addons.mockRejectedValue(new Error("network unavailable"));
    render(<IntegrationsView />);
    expect(await screen.findByText("Add-on inventory unavailable.")).toBeTruthy();
    expect(screen.queryByText(/Add-on inventory denied/)).toBeNull();
  });
});
