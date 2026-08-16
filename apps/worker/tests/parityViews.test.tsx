// @vitest-environment happy-dom

import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { WorkflowSummary } from "@wlilley93/boltrig-web-sdk";

const api = vi.hoisted(() => ({
  archiveWorkflow: vi.fn(),
  addons: vi.fn(),
  agentCapabilities: vi.fn(),
  capabilities: vi.fn(),
  auditTree: vi.fn(),
  assignWork: vi.fn(),
  capabilityChangelog: vi.fn(),
  channels: vi.fn(),
  createWorkflowTrigger: vi.fn(),
  createWork: vi.fn(),
  disableWorkflowTrigger: vi.fn(),
  disconnectIntegration: vi.fn(),
  executeWorkflow: vi.fn(),
  hitl: vi.fn(),
  integrationCatalogue: vi.fn(),
  integrationConnectionHealth: vi.fn(),
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
  mcpServers: vi.fn(),
  modelEndpoints: vi.fn(),
  permanentFleet: vi.fn(),
  applyPermanentFleet: vi.fn(),
  runs: vi.fn(),
  runTopology: vi.fn(),
  scheduleWorkflow: vi.fn(),
  restoreWorkflow: vi.fn(),
  rotateWorkflowTriggerSecret: vi.fn(),
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

import { AutomationsView, RoutinePicker } from "../src/components/AutomationView";
import { IntegrationsView } from "../src/components/IntegrationsView";
import {
  AgentsView,
  KnowledgeView,
  MemoryView,
  RunsView,
  WorkView,
} from "../src/components/ParityViews";

interface Deferred<T> {
  promise: Promise<T>;
  resolve(value: T): void;
  reject(reason: unknown): void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((accept, refuse) => {
    resolve = accept;
    reject = refuse;
  });
  return { promise, reject, resolve };
}

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
  // The Agents table derives its only real "asking" signal from the pending
  // Inbox list; an empty list means no waiting state is claimed.
  api.hitl.mockResolvedValue({ requests: [] });
  api.capabilityChangelog.mockResolvedValue({ changes: [] });
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
    expect(await screen.findByText(/waiting for approval in the originating chat/)).toBeTruthy();
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

  it("keeps an in-progress owner edit through a same-item upstream refresh, and submits the TYPED value", async () => {
    // The defect this pins: WorkDetail's sync effect reset owner/parent/status
    // whenever ANY of the item's fields changed, so a background refresh
    // mid-edit silently replaced the typed owner and the next Assign submitted
    // the OLD value - an approval collected for an action the user never asked
    // for. The fix reconciles only non-dirty fields on a same-item refresh.
    const item = {
      id: "work-a",
      intent: "Root task",
      status: "pending",
      owner_member: "engineering",
      source: "internal",
    };
    api.work.mockResolvedValue({ items: [item], next_cursor: null });
    // The refetch after the upstream mutation must RESOLVE THE CHANGED ITEM -
    // with an unchanged-item mock, React batches the transient merge and the
    // refetch into one render, the sync effect never re-fires, and this test
    // passed against the defect it exists to catch (measured: one SYNC-EFFECT
    // log for the whole flow). Production timing renders both.
    api.workDetail
      .mockResolvedValueOnce({ item, children: [], audit: [] })
      .mockResolvedValue({
        item: { ...item, status: "blocked" },
        children: [],
        audit: [],
      });
    // The upstream change: a status transition lands while the owner edit is
    // in progress. Its result carries the OLD owner_member, which is exactly
    // what used to clobber the input.
    api.transitionWork.mockResolvedValue({
      status: "ok",
      item: { ...item, status: "blocked" },
    });
    api.assignWork.mockResolvedValue({
      status: "ok",
      item: { ...item, status: "blocked", owner_member: "operations" },
    });

    render(<WorkView />);
    fireEvent.click(await screen.findByRole("button", { name: /Root task/ }));

    // 1. Start editing the owner - do NOT submit.
    fireEvent.change(await screen.findByLabelText("Owner"), {
      target: { value: "operations" },
    });

    // 2. A different mutation completes and refreshes the SAME item upstream.
    fireEvent.change(screen.getByLabelText("Status"), {
      target: { value: "blocked" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Change status" }));
    await screen.findByText(/Status updated to blocked/);

    // 3. The in-progress edit survived the refresh...
    expect((screen.getByLabelText("Owner") as HTMLInputElement).value)
      .toBe("operations");

    // 4. ...and Assign submits the TYPED value, not the stale canonical one.
    fireEvent.click(screen.getByRole("button", { name: "Assign" }));
    await waitFor(() => expect(api.assignWork).toHaveBeenCalledWith(
      "work-a", "operations", expect.any(String),
    ));
  });

  it("still resets the form wholesale when a DIFFERENT item is selected", async () => {
    // The negative control: keeping edits across a same-item refresh must not
    // leak them across items - selecting child work must show ITS fields.
    const parentItem = {
      id: "work-a",
      intent: "Root task",
      status: "pending",
      owner_member: "engineering",
      source: "internal",
    };
    const childItem = {
      id: "work-b",
      intent: "Child task",
      status: "pending",
      owner_member: "support",
      source: "internal",
    };
    api.work.mockResolvedValue({ items: [parentItem], next_cursor: null });
    api.workDetail
      .mockResolvedValueOnce({ item: parentItem, children: [childItem], audit: [] })
      .mockResolvedValueOnce({ item: childItem, children: [], audit: [] });

    render(<WorkView />);
    fireEvent.click(await screen.findByRole("button", { name: /Root task/ }));
    fireEvent.change(await screen.findByLabelText("Owner"), {
      target: { value: "half-typed-edit" },
    });
    fireEvent.click(await screen.findByRole("button", { name: /Child task/ }));

    await waitFor(() => expect(
      (screen.getByLabelText("Owner") as HTMLInputElement).value,
    ).toBe("support"));
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
  it("keeps provider governance in Settings and the decided two-tab Knowledge surface", async () => {
    api.knowledgeAssets.mockResolvedValue({
      assets: [],
      next_offset: null,
    });

    render(<KnowledgeView />);

    expect(await screen.findByRole("button", { name: "Files" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "What it remembers" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Providers" })).toBeNull();
    expect(api.knowledgeProviders).not.toHaveBeenCalled();
    expect(api.setKnowledgeProvider).not.toHaveBeenCalled();
  });

  it("retains the decided Quoted and Size columns with honest unavailable values", async () => {
    const asset = {
      id: "asset-columns",
      title: "Source columns",
      filename: "source-columns.txt",
      asset_type: "text",
      revision_id: "revision-columns",
      source_kind: "upload",
      segment_count: 3,
      created_at: "2026-01-01T00:00:00Z",
    };
    api.knowledgeAssets.mockResolvedValue({
      assets: [asset],
      next_offset: null,
    });

    render(<KnowledgeView />);

    expect(await screen.findByText("Quoted")).toBeTruthy();
    expect(screen.getByText("Size")).toBeTruthy();
    expect(screen.getByLabelText("Quoted count unavailable").textContent).toBe("—");
    expect(screen.getByLabelText("File size unavailable").textContent).toBe("—");
  });

  it("replays only the exact approved source erasure from the detail rail", async () => {
    const asset = {
      id: "asset-a",
      title: "Source A",
      filename: "source-a.txt",
      asset_type: "text",
      revision_id: "revision-a",
      source_kind: "upload",
      segment_count: 1,
      created_at: "2026-01-01T00:00:00Z",
    };
    api.knowledgeAssets.mockResolvedValue({
      assets: [asset],
      next_offset: null,
    });
    api.knowledgeAsset.mockResolvedValue({
      asset,
      segments: [],
      projections: [],
      provenance: { source_kind: "upload" },
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
    // The remove affordance lives on the selected file's rail and keeps the
    // governed two-step arm before the kernel is asked anything.
    fireEvent.click(await screen.findByRole("button", { name: /Source A/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Remove this file" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm removal" }));
    fireEvent.click(await screen.findByRole("button", {
      name: "Check approval and apply exact change",
    }));

    await waitFor(() => expect(api.eraseKnowledgeAsset).toHaveBeenLastCalledWith(
      "asset-a",
      "approval-erase",
    ));
    expect(await screen.findByText("The source was erased.")).toBeTruthy();
  });

  it("sends one permanent-erasure request while a deferred confirmation is pending", async () => {
    const asset = {
      id: "asset-deferred-erase",
      title: "Deferred source",
      filename: "deferred-source.txt",
      asset_type: "text",
      revision_id: "revision-deferred",
      source_kind: "upload",
      segment_count: 1,
      created_at: "2026-01-01T00:00:00Z",
    };
    api.knowledgeAssets.mockResolvedValue({ assets: [asset], next_offset: null });
    api.knowledgeAsset.mockResolvedValue({
      asset,
      segments: [],
      projections: [],
      provenance: { source_kind: "upload" },
    });
    let finishErase!: (result: {
      status: string;
      asset_id: string;
      operation_status: string;
    }) => void;
    api.eraseKnowledgeAsset.mockImplementation(() => new Promise((resolve) => {
      finishErase = resolve;
    }));

    render(<KnowledgeView />);
    fireEvent.click(await screen.findByRole("button", { name: /Deferred source/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Remove this file" }));
    const confirm = screen.getByRole("button", { name: "Confirm removal" });
    fireEvent.click(confirm);
    fireEvent.click(confirm);

    const pending = await screen.findByRole("button", { name: "Removing…" });
    expect((pending as HTMLButtonElement).disabled).toBe(true);
    expect(api.eraseKnowledgeAsset).toHaveBeenCalledTimes(1);
    expect(api.eraseKnowledgeAsset).toHaveBeenCalledWith("asset-deferred-erase");

    finishErase({
      status: "ok",
      asset_id: "asset-deferred-erase",
      operation_status: "erased",
    });
    expect(await screen.findByText("The source was erased.")).toBeTruthy();
  });

  it("keeps a rejected permanent-erasure confirmation armed for an explicit retry", async () => {
    const asset = {
      id: "asset-rejected-erase",
      title: "Retry source",
      filename: "retry-source.txt",
      asset_type: "text",
      revision_id: "revision-retry",
      source_kind: "upload",
      segment_count: 1,
      created_at: "2026-01-01T00:00:00Z",
    };
    api.knowledgeAssets.mockResolvedValue({ assets: [asset], next_offset: null });
    api.knowledgeAsset.mockResolvedValue({
      asset,
      segments: [],
      projections: [],
      provenance: { source_kind: "upload" },
    });
    api.eraseKnowledgeAsset
      .mockRejectedValueOnce(new Error("request unavailable"))
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval-retry-erase",
      });

    render(<KnowledgeView />);
    fireEvent.click(await screen.findByRole("button", { name: /Retry source/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Remove this file" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm removal" }));

    expect(await screen.findByText(
      "Removal could not be confirmed. No success is shown; confirm removal to retry.",
    )).toBeTruthy();
    const retry = screen.getByRole("button", { name: "Confirm removal" });
    expect((retry as HTMLButtonElement).disabled).toBe(false);
    expect(retry.getAttribute("data-armed")).toBe("true");
    expect(api.eraseKnowledgeAsset).toHaveBeenCalledTimes(1);

    fireEvent.click(retry);
    expect(await screen.findByText(
      "Erasure is waiting for approval in the originating chat.",
    )).toBeTruthy();
    expect(api.eraseKnowledgeAsset).toHaveBeenCalledTimes(2);
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

  function previewWorkflow(id: string): WorkflowSummary {
    return {
      id,
      version: "1.0.0",
      source: "precreated",
      intent_tags: [],
      status: "active",
      schedule: null,
    };
  }

  it("keeps a routine preview neutral while its detail is loading", () => {
    api.workflow.mockImplementation(() => new Promise(() => undefined));

    render(
      <RoutinePicker
        onNew={vi.fn()}
        onOpen={vi.fn()}
        stats={{}}
        workflows={[previewWorkflow("loading-preview")]}
      />,
    );

    expect(screen.getByText("Loading preview")).toBeTruthy();
    expect(screen.queryByText("manual")).toBeNull();
    expect(screen.queryByRole("img", { name: "This routine has no steps yet" }))
      .toBeNull();
    expect(screen.queryByRole("button", { name: /Retry preview/ })).toBeNull();
  });

  it("claims a canonical empty routine only after a ready detail read", async () => {
    const workflow = previewWorkflow("empty-preview");
    api.workflow.mockResolvedValue({
      ...workflow,
      definition: { steps: [] },
    });

    render(
      <RoutinePicker
        onNew={vi.fn()}
        onOpen={vi.fn()}
        stats={{}}
        workflows={[workflow]}
      />,
    );

    expect(await screen.findByRole("img", {
      name: "This routine has no steps yet",
    })).toBeTruthy();
    expect(screen.getByText("manual")).toBeTruthy();
    expect(screen.queryByText("Preview unavailable")).toBeNull();
  });

  it("keeps a failed preview neutral while leaving the detail path available", async () => {
    const workflow = previewWorkflow("failed-preview");
    const onOpen = vi.fn();
    api.workflow.mockRejectedValue(new Error("detail unavailable"));

    const { container } = render(
      <RoutinePicker
        onNew={vi.fn()}
        onOpen={onOpen}
        stats={{}}
        workflows={[workflow]}
      />,
    );

    expect(await screen.findByText("Preview unavailable")).toBeTruthy();
    expect(screen.queryByText("manual")).toBeNull();
    expect(screen.queryByRole("img", { name: "This routine has no steps yet" }))
      .toBeNull();
    expect(screen.getByRole("button", {
      name: "Retry preview for failed-preview",
    })).toBeTruthy();

    fireEvent.click(container.querySelector<HTMLButtonElement>(".routine-card")!);
    expect(onOpen).toHaveBeenCalledWith("failed-preview", undefined);
  });

  it("recovers a failed preview through its bounded Retry action", async () => {
    const workflow = previewWorkflow("retry-preview");
    const onOpen = vi.fn();
    api.workflow
      .mockRejectedValueOnce(new Error("detail unavailable"))
      .mockResolvedValueOnce({
        ...workflow,
        definition: {
          steps: [{ id: "step-1", action: "work.read", parents: [] }],
        },
      });

    render(
      <RoutinePicker
        onNew={vi.fn()}
        onOpen={onOpen}
        stats={{}}
        workflows={[workflow]}
      />,
    );

    fireEvent.click(await screen.findByRole("button", {
      name: "Retry preview for retry-preview",
    }));
    expect(screen.getByText("Loading preview")).toBeTruthy();
    expect(await screen.findByRole("img", { name: "1 step" })).toBeTruthy();
    expect(screen.getByText("manual")).toBeTruthy();
    expect(screen.queryByText("Preview unavailable")).toBeNull();
    expect(api.workflow).toHaveBeenCalledTimes(2);
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("opens a routine in the viewport editor", async () => {
    api.workflows.mockResolvedValue({ workflows: [] });
    api.capabilities.mockResolvedValue({ verbs: [] });
    api.workflowStats.mockResolvedValue({ stats: [] });

    const { container } = render(<AutomationsView />);
    fireEvent.click(await screen.findByRole("button", { name: "New routine" }));

    const viewport = screen.getByRole("region", { name: "Routine editor viewport" });
    expect(viewport.closest(".automation-editor-page")).toBeTruthy();
    expect(container.querySelector(".console-page")).toBeNull();
    expect(screen.queryByLabelText("Workflow library")).toBeNull();
    expect(within(viewport).getByRole("main", { name: "Routine workflow editor" }))
      .toBeTruthy();
    expect(within(viewport).getByRole("region", { name: "Routine canvas editor" }))
      .toBeTruthy();
    expect(within(viewport).getByLabelText("Routine rail")).toBeTruthy();
    expect(within(viewport).getByRole("region", { name: "Routine validation footer" }))
      .toBeTruthy();
    expect(within(viewport).getByRole("toolbar", { name: "Routine canvas controls" }))
      .toBeTruthy();
    expect(within(viewport).getByText(
      "This is the saved routine. Every action still follows your access and approval rules.",
    )).toBeTruthy();
    expect(within(viewport).queryByText(/parents\[\]|engine walks|saved spec/i)).toBeNull();
  });

  it("guards a dirty new routine, restores Back focus on Cancel, and discards to the picker", async () => {
    api.workflows.mockResolvedValue({ workflows: [] });
    api.capabilities.mockResolvedValue({ verbs: [] });
    api.workflowStats.mockResolvedValue({ stats: [] });

    const { container } = render(<AutomationsView />);
    fireEvent.click(await screen.findByRole("button", { name: "New routine" }));

    const back = screen.getByRole("button", { name: "Routines" });
    back.focus();
    fireEvent.click(back);

    const dialog = screen.getByRole("alertdialog", {
      name: "Discard unsaved changes?",
    });
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(within(dialog).getByText(/changes that have not been saved/)).toBeTruthy();
    const cancel = within(dialog).getByRole("button", { name: "Cancel" });
    const confirm = within(dialog).getByRole("button", { name: "Discard changes" });
    expect(document.activeElement).toBe(cancel);

    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(confirm);
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(document.activeElement).toBe(cancel);
    fireEvent.click(cancel);

    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.getByRole("main", { name: "Routine workflow editor" })).toBeTruthy();
    expect(document.activeElement).toBe(back);

    fireEvent.click(back);
    fireEvent.click(screen.getByRole("button", { name: "Discard changes" }));

    expect(await screen.findByRole("heading", { name: "Routines" })).toBeTruthy();
    expect(container.querySelector(".automation-editor-page")).toBeNull();
    expect(container.querySelector(".console-page")).toBeTruthy();
  });

  it("guards both Back and explicit Discard for a dirty existing routine", async () => {
    const saved = {
      id: "existing-routine",
      version: "1.0.0",
      source: "precreated",
      intent_tags: [],
      definition: { steps: [] },
      status: "active",
      schedule: null,
    };
    mockAutomationDetail(saved);

    render(<AutomationsView />);
    fireEvent.click(await screen.findByRole("button", { name: /existing-routine/ }));
    await screen.findByRole("main", { name: "Routine workflow editor" });
    fireEvent.change(screen.getByLabelText("Workflow id"), {
      target: { value: "existing-routine-edited" },
    });

    const back = screen.getByRole("button", { name: "Routines" });
    back.focus();
    fireEvent.click(back);
    expect(screen.getByRole("alertdialog", { name: "Discard unsaved changes?" }))
      .toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect((screen.getByLabelText("Workflow id") as HTMLInputElement).value)
      .toBe("existing-routine-edited");
    expect(document.activeElement).toBe(back);

    const discard = screen.getByRole("button", { name: "Discard" });
    discard.focus();
    fireEvent.click(discard);
    expect(screen.getByRole("alertdialog", { name: "Discard unsaved changes?" }))
      .toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Discard changes" }));

    expect(await screen.findByRole("heading", { name: "Routines" })).toBeTruthy();
    expect(screen.queryByRole("main", { name: "Routine workflow editor" })).toBeNull();
  });

  it("closes a clean existing routine immediately", async () => {
    const saved = {
      id: "clean-routine",
      version: "1.0.0",
      source: "precreated",
      intent_tags: [],
      definition: { steps: [] },
      status: "active",
      schedule: null,
    };
    mockAutomationDetail(saved);

    render(<AutomationsView />);
    fireEvent.click(await screen.findByRole("button", { name: /clean-routine/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Routines" }));

    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(await screen.findByRole("heading", { name: "Routines" })).toBeTruthy();
    expect(screen.queryByRole("main", { name: "Routine workflow editor" })).toBeNull();
  });

  it("authors a dependency step through the canonical workflow upsert", async () => {
    api.workflows.mockResolvedValue({ workflows: [] });
    api.capabilities.mockResolvedValue({
      verbs: [{ id: "work.create", noun: "work", consequence: "high" }],
    });
    api.upsertWorkflow.mockResolvedValue({ status: "ok", id: "daily-review" });

    render(<AutomationsView />);
    await waitFor(() => expect(api.capabilities).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "New routine" }));
    fireEvent.change(screen.getByLabelText("Workflow id"), {
      target: { value: "daily-review" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add step" }));

    expect(screen.getByLabelText("Step id")).toBeTruthy();
    expect((screen.getByLabelText("Action") as HTMLInputElement).value).toBe("work.create");
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
    fireEvent.click(await screen.findByRole("button", { name: "New routine" }));
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

  it("reports a kernel refusal for immediate execution instead of inventing a run", async () => {
    const base = {
      id: "refused-run",
      version: "1.0.0",
      source: "precreated",
      intent_tags: [],
      definition: { steps: [] },
      status: "active",
      schedule: null,
    };
    mockAutomationDetail(base);
    api.executeWorkflow
      .mockResolvedValueOnce({ status: "denied", reason: "workflow_execution_denied" })
      .mockResolvedValueOnce({ error: "unknown_workflow" });

    render(<AutomationsView />);
    fireEvent.click(await screen.findByRole("button", { name: /refused-run/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Run now" }));
    expect(await screen.findByText("workflow_execution_denied")).toBeTruthy();
    expect(screen.queryByText(/Run undefined/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Run now" }));
    expect(await screen.findByText("unknown_workflow")).toBeTruthy();
  });

  it("reports a refused execute replay instead of claiming the approved run applied", async () => {
    const base = {
      id: "revoked-run",
      version: "1.0.0",
      source: "precreated",
      intent_tags: [],
      definition: { steps: [] },
      status: "active",
      schedule: null,
    };
    mockAutomationDetail(base);
    api.executeWorkflow
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval-execute",
      })
      .mockResolvedValueOnce({ status: "denied", reason: "grant_revoked" });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });

    render(<AutomationsView />);
    fireEvent.click(await screen.findByRole("button", { name: /revoked-run/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Run now" }));
    fireEvent.click(await screen.findByRole("button", {
      name: "Check approval and apply exact change",
    }));
    await waitFor(() => expect(api.executeWorkflow).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("grant_revoked")).toBeTruthy();
    expect(screen.queryByText(/Run undefined/)).toBeNull();
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
      await screen.findByText("Waiting for a decision in the originating chat"),
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
      await screen.findByText("Waiting for a decision in the originating chat"),
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
      // The Routines picker reads each routine's definition to draw its own
      // graph on the card, so one detail read happens before anything is
      // selected. The editor's sequence below is unchanged.
      .mockResolvedValueOnce({
        ...base,
        status: "active",
        schedule: { type: "cron", cron: "0 9 * * 1-5", timezone: "UTC" },
      })
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

  it("checks and finalizes an approved webhook in the same mounted editor", async () => {
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

    render(<AutomationsView />);
    fireEvent.click(await screen.findByRole("button", { name: /event-review/i }));
    const mountedEditor = await screen.findByLabelText("Routine editor viewport");
    fireEvent.change(await screen.findByLabelText("Trigger binding name"), {
      target: { value: "provider events" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Bind source" }));

    await waitFor(() => expect(api.createWorkflowTrigger).toHaveBeenCalledWith(
      base.id,
      { name: "provider events", source: "webhook" },
    ));
    expect(await screen.findByText(/Finalize the approved webhook binding/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Check approval status" })).toBeTruthy();
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
    fireEvent.click(screen.getByRole("button", { name: "Check approval status" }));
    await waitFor(() => expect(api.workflowTriggerFinalizations).toHaveBeenLastCalledWith(
      base.id,
    ));
    expect(await screen.findByText(/approval is ready/)).toBeTruthy();
    expect(screen.getByLabelText("Routine editor viewport")).toBe(mountedEditor);
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

  it("checks and finalizes an approved secret rotation in place", async () => {
    const base = {
      id: "rotating-hook",
      version: "1.0.0",
      source: "precreated",
      intent_tags: [],
      definition: { steps: [] },
      status: "active",
    };
    const trigger = {
      id: "trigger-webhook",
      workflow_id: base.id,
      workspace_id: null,
      name: "provider webhook",
      source: "webhook",
      owner_id: "author",
      channel_id: null,
      enabled: true,
      secret_configured: true,
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
    api.rotateWorkflowTriggerSecret
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "hitl-rotate-webhook",
      })
      .mockResolvedValueOnce({
        status: "ok",
        trigger_id: trigger.id,
        workflow_id: base.id,
        secret: "wft_rotated-once",
      });

    render(<AutomationsView />);
    fireEvent.click(await screen.findByRole("button", { name: /rotating-hook/i }));
    fireEvent.click(await screen.findByRole("button", { name: "Rotate secret" }));
    expect(await screen.findByText(/Finalize the approved secret rotation/)).toBeTruthy();

    api.workflowTriggerFinalizations.mockResolvedValue({
      workflow_id: base.id,
      finalizations: [{
        request_id: "hitl-rotate-webhook",
        action: "rotate",
        state: "ready",
        trigger_id: trigger.id,
      }],
    });
    fireEvent.click(screen.getByRole("button", { name: "Check approval status" }));
    expect(await screen.findByRole("button", { name: "Finalize after approval" }))
      .toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Finalize after approval" }));

    await waitFor(() => expect(api.rotateWorkflowTriggerSecret).toHaveBeenLastCalledWith(
      base.id,
      trigger.id,
      "hitl-rotate-webhook",
    ));
    expect(await screen.findByText("wft_rotated-once")).toBeTruthy();
  });

  it("fails closed when a pending webhook has no approval request id", async () => {
    const base = {
      id: "missing-webhook-approval",
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
    api.workflowTriggers.mockResolvedValue({ workflow_id: base.id, triggers: [] });
    api.channels.mockResolvedValue({ channels: [] });
    api.createWorkflowTrigger.mockResolvedValue({ status: "pending_human" });

    render(<AutomationsView />);
    fireEvent.click(await screen.findByRole("button", {
      name: /missing-webhook-approval/i,
    }));
    fireEvent.change(await screen.findByLabelText("Trigger binding name"), {
      target: { value: "missing approval" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Bind source" }));

    expect(await screen.findByText(/no request id was returned/i)).toBeTruthy();
    expect((screen.getByRole("button", {
      name: "Approval check unavailable",
    }) as HTMLButtonElement).disabled).toBe(true);
    expect(api.createWorkflowTrigger).toHaveBeenCalledTimes(1);
  });

  it("fails closed when the exact webhook approval read is unavailable", async () => {
    const base = {
      id: "unavailable-webhook-approval",
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
    api.workflowTriggers.mockResolvedValue({ workflow_id: base.id, triggers: [] });
    api.channels.mockResolvedValue({ channels: [] });
    api.createWorkflowTrigger.mockResolvedValue({
      status: "pending_human",
      hitl_request_id: "hitl-unavailable-webhook",
    });

    render(<AutomationsView />);
    fireEvent.click(await screen.findByRole("button", {
      name: /unavailable-webhook-approval/i,
    }));
    fireEvent.change(await screen.findByLabelText("Trigger binding name"), {
      target: { value: "unavailable approval" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Bind source" }));
    await screen.findByRole("button", { name: "Check approval status" });

    api.workflowTriggerFinalizations.mockRejectedValue(new Error("unavailable"));
    fireEvent.click(screen.getByRole("button", { name: "Check approval status" }));

    expect(await screen.findByText(
      "Webhook binding approval status is unavailable. No trigger change is inferred.",
    )).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry approval check" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Finalize after approval" })).toBeNull();
    expect(api.createWorkflowTrigger).toHaveBeenCalledTimes(1);
  });

  it.each(["success", "error"] as const)(
    "ignores a late trigger-delivery %s after workflow A moves to workflow B",
    async (lateOutcome) => {
      const workflows = ["delivery-a", "delivery-b"].map((id) => ({
        id,
        version: "1.0.0",
        source: "precreated",
        intent_tags: [],
        definition: { steps: [] },
        status: "active",
      }));
      const triggerFor = (workflowId: string) => ({
        id: `trigger-${workflowId}`,
        workflow_id: workflowId,
        workspace_id: null,
        name: `${workflowId} webhook`,
        source: "webhook",
        owner_id: "author",
        channel_id: null,
        enabled: true,
        secret_configured: true,
        created_at: null,
        updated_at: null,
      });
      const deliveryA = deferred<{
        workflow_id: string;
        trigger_id: string;
        deliveries: Array<{
          trigger_id: string;
          event_digest: string;
          status: string;
          authority_subject: string;
          run_id: null;
          hitl_request_id: null;
          reason: null;
          created_at: null;
        }>;
      }>();
      const deliveryB = deferred<{
        workflow_id: string;
        trigger_id: string;
        deliveries: Array<{
          trigger_id: string;
          event_digest: string;
          status: string;
          authority_subject: string;
          run_id: null;
          hitl_request_id: null;
          reason: null;
          created_at: null;
        }>;
      }>();
      api.workflows.mockResolvedValue({ workflows });
      api.capabilities.mockResolvedValue({ verbs: [] });
      api.workflowStats.mockResolvedValue({ stats: [] });
      api.workflow.mockImplementation(async (id: string) => (
        workflows.find((workflow) => workflow.id === id)
      ));
      api.workflowRuns.mockImplementation(async (id: string) => ({
        workflow_id: id,
        runs: [],
      }));
      api.workflowTriggers.mockImplementation(async (id: string) => ({
        workflow_id: id,
        triggers: [triggerFor(id)],
      }));
      api.channels.mockResolvedValue({ channels: [] });
      api.workflowTriggerDeliveries.mockImplementation((workflowId: string) => (
        workflowId === "delivery-a" ? deliveryA.promise : deliveryB.promise
      ));

      render(<AutomationsView />);
      fireEvent.click(await screen.findByRole("button", { name: /delivery-a/i }));
      fireEvent.click(await screen.findByRole("button", { name: "Delivery history" }));
      await waitFor(() => expect(api.workflowTriggerDeliveries).toHaveBeenCalledWith(
        "delivery-a",
        "trigger-delivery-a",
      ));

      fireEvent.click(screen.getByRole("button", { name: "Routines" }));
      fireEvent.click(await screen.findByRole("button", { name: /delivery-b/i }));
      fireEvent.click(await screen.findByRole("button", { name: "Delivery history" }));
      await waitFor(() => expect(api.workflowTriggerDeliveries).toHaveBeenCalledWith(
        "delivery-b",
        "trigger-delivery-b",
      ));
      await act(async () => deliveryB.resolve({
        workflow_id: "delivery-b",
        trigger_id: "trigger-delivery-b",
        deliveries: [{
          trigger_id: "trigger-delivery-b",
          event_digest: "b".repeat(64),
          status: "completed",
          authority_subject: "sender-b",
          run_id: null,
          hitl_request_id: null,
          reason: null,
          created_at: null,
        }],
      }));
      expect(await screen.findByText("sender-b")).toBeTruthy();

      await act(async () => {
        if (lateOutcome === "success") {
          deliveryA.resolve({
            workflow_id: "delivery-a",
            trigger_id: "trigger-delivery-a",
            deliveries: [{
              trigger_id: "trigger-delivery-a",
              event_digest: "a".repeat(64),
              status: "completed",
              authority_subject: "sender-a",
              run_id: null,
              hitl_request_id: null,
              reason: null,
              created_at: null,
            }],
          });
        } else {
          deliveryA.reject(new Error("late A failed"));
        }
      });

      expect(screen.getByText("sender-b")).toBeTruthy();
      expect(screen.queryByText("sender-a")).toBeNull();
      expect(screen.queryByText(
        "Trigger delivery history is unavailable in this workspace.",
      )).toBeNull();
    },
  );

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
  it("stages supported agent creation methods before opening the governed author", async () => {
    api.agentCapabilities.mockResolvedValue({ agent_capabilities: [] });

    render(<AgentsView />);
    fireEvent.click(await screen.findByRole("button", { name: "New agent" }));

    const modal = screen.getByRole("dialog", { name: "New agent" });
    expect((within(modal).getByRole("button", { name: /Copy one that works/ }) as HTMLButtonElement).disabled).toBe(true);
    expect((within(modal).getByRole("button", { name: /Describe the job/ }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(modal).getByRole("button", { name: /Start from nothing/ }));
    expect(await screen.findByText("Create an agent")).toBeTruthy();
  });

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
    fireEvent.click(await screen.findByRole("button", { name: "Inspect chief-of-staff" }));
    fireEvent.click(screen.getByRole("button", { name: "Edit topology" }));
    fireEvent.change(screen.getAllByLabelText("Purpose")[1], {
      target: { value: "Own research and synthesis" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Request hierarchy change" }));

    await waitFor(() => expect(api.applyPermanentFleet).toHaveBeenCalled());
    expect(api.applyPermanentFleet.mock.calls[0][0].departments[0].purpose)
      .toBe("Own research and synthesis");
    expect(await screen.findByText(/No running worker was mutated/)).toBeTruthy();
  });

  it("draws the deterministic fleet while keeping unavailable facts explicit", async () => {
    api.agentCapabilities.mockResolvedValue({ agent_capabilities: [] });
    api.permanentFleet.mockResolvedValue({
      status: "configured",
      hierarchy: {
        chief: {
          name: "chief-of-staff",
          routing_id: "cos",
          purpose: "Coordinate approved work",
          brief: "",
          runtime: "codex",
          model_endpoint: null,
          supported_skills: ["*"],
          max_depth: 4,
          cost_tier: "standard",
          budget: null,
        },
        departments: [{
          name: "research-head",
          routing_id: "research",
          purpose: "Own research",
          brief: "",
          runtime: "codex",
          model_endpoint: null,
          supported_skills: ["research/*"],
          max_depth: 3,
          cost_tier: "standard",
          budget: null,
        }],
      },
      generation: "fleet-generation-7",
      revision: 7,
      apply_state: "restart_required",
      observations: [],
    });

    const { container } = render(<AgentsView />);

    expect(await screen.findByText("Spend unavailable")).toBeTruthy();
    expect(screen.getByText("working unknown")).toBeTruthy();
    expect(screen.getByText("Authority is not exposed by this fleet response")).toBeTruthy();
    expect(screen.queryByText("£325.10")).toBeNull();
    expect(await screen.findByRole("button", { name: "Inspect chief-of-staff" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Inspect research-head" })).toBeTruthy();
    expect(container.querySelectorAll(".fleet-connectors path")).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Inspect research-head" }));
    const inspector = screen.getByRole("dialog", { name: "research-head fleet inspector" });
    expect(within(inspector).getByText("Mood")).toBeTruthy();
    expect(within(inspector).getByText("Kit")).toBeTruthy();
    expect(within(inspector).getAllByText("unavailable").length).toBeGreaterThanOrEqual(2);
    fireEvent.click(within(inspector).getByRole("button", { name: "Close fleet inspector" }));

    fireEvent.click(screen.getByRole("button", {
      name: "Start child profile handoff from research-head",
    }));
    expect(screen.getByRole("dialog", { name: "Create a profile from research-head" })).toBeTruthy();
    expect(screen.getByText(/does not store a parent edge/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Open profile author" }));
    expect(await screen.findByText("Create an agent")).toBeTruthy();
    expect(screen.getByText(/does not persist a parent edge/)).toBeTruthy();
  });

  it("reports waiting state as unknown when the scoped inbox cannot be read", async () => {
    api.agentCapabilities.mockResolvedValue({ agent_capabilities: [] });
    api.hitl.mockRejectedValue(new Error("not available"));

    render(<AgentsView />);

    expect(await screen.findByText("waiting unknown")).toBeTruthy();
    expect(screen.queryByText("0 waiting on you")).toBeNull();
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
    const renderedBadge = familiar.querySelector<HTMLElement>(".familiar-orb");
    expect(renderedBadge?.dataset.renderer).toBe("badge");
    expect(renderedBadge?.getAttribute("style")).toContain("#ffedd5");
    expect(renderedBadge?.getAttribute("style")).toContain("#7c2d12");
    expect(familiar.querySelector(".familiar-stage")).toBeNull();
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
    expect(await screen.findByText("retired")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Inspect archivist" }));
    expect(screen.getByText("standard")).toBeTruthy();
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
    fireEvent.click(await screen.findByRole("button", { name: "Inspect archivist" }));
    fireEvent.click(screen.getByRole("button", { name: "Restore profile" }));
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
    health: "ok",
    credential_ref_present: true,
    accounts: [{ id: "support", label: "Tickets", selected: true }],
    enabled_tools: ["tickets.read"],
    last_checked_at: "2026-08-11T04:00:00Z",
    created_at: "2026-07-29T00:00:00Z",
  };
  const failedMcpServer = {
    id: "vendor-portal",
    config_revision: 3,
    version: "1.0.0",
    source: "workspace",
    state: "active",
    activated: true,
    runtime_loaded: true,
    endpoint: {
      origin: "https://vendor.example",
      path_redacted: true,
      internal_egress_allowed: false,
    },
    credential_configured: true,
    recorded_health: "degraded",
    health: {
      status: "degraded",
      source: "durable_probe",
      checked_at: "2026-08-11T04:20:00Z",
    },
    operability: { status: "degraded", reason: "probe_failed" },
    last_probe: {
      checked_at: "2026-08-11T04:20:00Z",
      outcome: "failed",
      failure_code: "egress_denied",
      tool_count: 0,
    },
    tool_snapshot: {
      status: "never_discovered",
      observed_at: null,
      count: 0,
      publication_status: "never_discovered",
    },
    available_actions: ["probe", "retire"],
  };

  beforeEach(() => {
    api.addons.mockResolvedValue({
      scope: { tenant_id: "tenant-a", workspace_id: "workspace-a" },
      addons: [],
    });
    api.mcpServers.mockResolvedValue({ servers: [], truncated: false });
  });

  it("labels the catalogue as preview and keeps setup disabled without kernel routes", async () => {
    api.integrationCatalogue.mockRejectedValue(new Error("not found"));
    api.integrationConnections.mockRejectedValue(new Error("not found"));

    render(<IntegrationsView />);
    expect(screen.getByLabelText("Search integrations")).toBeTruthy();
    await screen.findByText(/Plugin setup is unavailable/);
    expect(screen.getAllByRole("button", { name: /^Open .* details$/ })).toHaveLength(40);
    expect(screen.getByRole("heading", { name: "Work tracking" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Open Slack details" }));
    expect((screen.getByRole("button", { name: "Setup unavailable" }) as HTMLButtonElement).disabled).toBe(true);
    expect(api.startIntegrationOAuth).not.toHaveBeenCalled();
  });

  it("keeps reviewed preview entries when the authoritative catalogue is empty", async () => {
    api.integrationCatalogue.mockResolvedValue({ integrations: [] });
    api.integrationConnections.mockResolvedValue({ connections: [] });

    render(<IntegrationsView />);
    await waitFor(() => expect(api.integrationConnections).toHaveBeenCalled());
    expect(screen.getAllByRole("button", { name: /^Open .* details$/ })).toHaveLength(40);
    expect(screen.getByText("0 connected of 40")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Files and design" })).toBeTruthy();
  });

  it("opens a simple searchable plugin picker and hands the choice to setup", async () => {
    api.integrationCatalogue.mockResolvedValue({ integrations: [ticketEntry] });
    api.integrationConnections.mockResolvedValue({ connections: [] });

    render(<IntegrationsView />);
    await waitFor(() => expect(api.integrationConnections).toHaveBeenCalled());
    const trigger = screen.getByRole("button", { name: "Add plugin" });
    trigger.focus();
    fireEvent.click(trigger);

    const dialog = screen.getByRole("dialog", { name: "Add a plugin" });
    expect(within(dialog).getByLabelText("Search plugins")).toBeTruthy();
    expect(within(dialog).queryByRole("button", { name: "Add Apollo" })).toBeNull();
    fireEvent.change(within(dialog).getByLabelText("Search plugins"), {
      target: { value: "Tickets" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add Tickets" }));

    expect(screen.queryByRole("dialog", { name: "Add a plugin" })).toBeNull();
    expect(await screen.findByRole("region", { name: "Tickets details" })).toBeTruthy();
    await waitFor(() => expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Close Tickets details" }),
    ));
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
    fireEvent.click(await screen.findByRole("button", { name: "Open Tickets details" }));
    await screen.findByText(/Current return state: browser callback unavailable/i);
    fireEvent.click(screen.getByRole("button", { name: "Open Tickets" }));

    expect(await screen.findByText(
      /no reviewed web OAuth callback contract/i,
    )).toBeTruthy();
    expect(screen.getByText(/Current return state: browser callback unavailable/i)).toBeTruthy();
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
    fireEvent.click(await screen.findByRole("button", { name: "Open Tickets details" }));
    fireEvent.click(screen.getByRole("button", { name: "Add the key" }));
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
    fireEvent.click(await screen.findByRole("button", { name: "Open Tickets details" }));
    fireEvent.click(await screen.findByRole("button", { name: "Revoke" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm revoke" }));
    fireEvent.click(await screen.findByRole("button", {
      name: "Check approval and apply exact change",
    }));

    await waitFor(() => expect(api.disconnectIntegration).toHaveBeenLastCalledWith(
      "conn-1",
      "hitl-revoke",
    ));
    expect(await screen.findByText("Tickets disconnected.")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Tickets details" })).toBeNull();
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
    fireEvent.click(await screen.findByRole("button", { name: "Open Tickets details" }));
    fireEvent.click(await screen.findByRole("button", { name: "Revoke" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm revoke" }));
    await screen.findByRole("button", {
      name: "Check approval and apply exact change",
    });

    fireEvent.click(screen.getByRole("button", { name: "Close Tickets details" }));

    expect(await screen.findByText("Tickets disconnection changed")).toBeTruthy();
    expect(screen.queryByRole("button", {
      name: "Check approval and apply exact change",
    })).toBeNull();
    expect(api.invokeApprovalState).not.toHaveBeenCalled();
    expect(api.disconnectIntegration).toHaveBeenCalledTimes(1);
  });

  it("groups the reported inventory and applies status, category, and search filters", async () => {
    const activeServer = {
      ...failedMcpServer,
      id: "opbox",
      recorded_health: "ok",
      health: {
        status: "ok",
        source: "durable_probe",
        checked_at: "2026-08-11T04:30:00Z",
      },
      operability: { status: "ready", reason: null },
      last_probe: {
        checked_at: "2026-08-11T04:30:00Z",
        outcome: "succeeded",
        failure_code: null,
        tool_count: 3,
      },
      tool_snapshot: {
        status: "snapshot",
        observed_at: "2026-08-11T04:30:00Z",
        count: 3,
        publication_status: "published",
      },
    };
    api.integrationCatalogue.mockResolvedValue({ integrations: [ticketEntry] });
    api.integrationConnections.mockResolvedValue({ connections: [ticketConnection] });
    api.mcpServers.mockResolvedValue({ servers: [activeServer], truncated: false });

    render(<IntegrationsView />);
    expect(await screen.findByText("2 connected of 42")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Your own servers" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Filters" }));
    fireEvent.click(screen.getByRole("button", { name: "Connected" }));
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.getByRole("button", { name: "Open Tickets details" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Open opbox server details" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Open Slack details" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Filters/ }));
    fireEvent.click(screen.getByRole("button", { name: "Filter by Work tracking" }));
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.getByRole("button", { name: "Open Tickets details" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Open opbox server details" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Filters/ }));
    fireEvent.click(screen.getByRole("button", { name: "Clear all" }));
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    fireEvent.change(screen.getByLabelText("Search integrations"), {
      target: { value: "opbox" },
    });
    expect(screen.getByRole("button", { name: "Open opbox server details" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Open Tickets details" })).toBeNull();
  });

  it("keeps certification, degraded health, MCP probe evidence, and custody claims separate", async () => {
    api.integrationCatalogue.mockResolvedValue({ integrations: [ticketEntry] });
    api.integrationConnections.mockResolvedValue({
      connections: [{ ...ticketConnection, health: "degraded" }],
    });
    api.mcpServers.mockResolvedValue({ servers: [failedMcpServer], truncated: false });

    render(<IntegrationsView />);
    expect(await screen.findByText("Two need you")).toBeTruthy();
    expect(screen.getByText("Reviewed")).toBeTruthy();
    expect(screen.getAllByText("Degraded")).toHaveLength(2);
    expect(screen.getByText(/Tickets is degraded/)).toBeTruthy();
    expect(screen.getByText(/vendor-portal's last probe failed \(egress denied\)/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Open Tickets details" }));
    expect(screen.getByText("reference present · custody not exposed")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Open vendor-portal server details" }));
    expect(screen.getByText("egress_denied")).toBeTruthy();
    expect(screen.getByText("configured · contents unavailable")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open MCP operations" }).getAttribute("href")).toBe("#/build/adapters");
    expect(screen.queryByText(/Nango/i)).toBeNull();
    expect(screen.queryByText(/held outside Boltrig/i)).toBeNull();
  });

  it("opens and focuses every reported issue from Look at both", async () => {
    api.integrationCatalogue.mockResolvedValue({ integrations: [ticketEntry] });
    api.integrationConnections.mockResolvedValue({
      connections: [{ ...ticketConnection, health: "degraded" }],
    });
    api.mcpServers.mockResolvedValue({ servers: [failedMcpServer], truncated: false });

    render(<IntegrationsView />);
    expect(await screen.findByText("Two need you")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Search integrations"), {
      target: { value: "Slack" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Look at both" }));

    expect((screen.getByLabelText("Search integrations") as HTMLInputElement).value).toBe("");
    expect(await screen.findByRole("region", { name: "Tickets details" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Open vendor-portal server details" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Open Slack details" })).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Close Tickets details" }),
    ));
    fireEvent.click(screen.getByRole("button", { name: "Close Tickets details" }));
    expect(screen.queryByRole("region", { name: "Tickets details" })).toBeNull();
    expect(screen.getByRole("button", { name: "Open Tickets details" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Open vendor-portal server details" })).toBeTruthy();
  });

  it("surfaces the canonical OAuth 409 without inventing a provider flow", async () => {
    api.integrationCatalogue.mockResolvedValue({
      integrations: [{ ...ticketEntry, auth: ["oauth2"], setup_contract: null }],
    });
    api.integrationConnections.mockResolvedValue({ connections: [] });
    api.startIntegrationOAuth.mockRejectedValue({
      status: 409,
      body: { reason: "oauth_provider_not_configured" },
    });

    render(<IntegrationsView />);
    fireEvent.click(await screen.findByRole("button", { name: "Open Tickets details" }));
    fireEvent.click(screen.getByRole("button", { name: "Open Tickets" }));

    expect(await screen.findByText(/no configured provider launch/i)).toBeTruthy();
    expect(screen.getByText(/no connection is assumed/i)).toBeTruthy();
  });

  it("refreshes health from the connection API and clears a real degraded alert", async () => {
    const degraded = { ...ticketConnection, health: "degraded" };
    api.integrationCatalogue.mockResolvedValue({ integrations: [ticketEntry] });
    api.integrationConnections.mockResolvedValue({ connections: [degraded] });
    api.integrationConnectionHealth.mockResolvedValue({
      connection: { ...ticketConnection, health: "ok", last_checked_at: "2026-08-11T04:45:00Z" },
    });

    render(<IntegrationsView />);
    expect(await screen.findByText("One needs you")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Open Tickets details" }));
    fireEvent.click(screen.getByRole("button", { name: "Check it now" }));

    await waitFor(() => expect(api.integrationConnectionHealth).toHaveBeenCalledWith("conn-1"));
    expect(await screen.findByText("Tickets health is connected.")).toBeTruthy();
    expect(screen.queryByText("One needs you")).toBeNull();
  });

  it("does not allow a revoke to race an in-flight connection health probe", async () => {
    let resolveHealth!: (value: { connection: typeof ticketConnection }) => void;
    api.integrationCatalogue.mockResolvedValue({ integrations: [ticketEntry] });
    api.integrationConnections.mockResolvedValue({ connections: [ticketConnection] });
    api.integrationConnectionHealth.mockReturnValue(new Promise((resolve) => {
      resolveHealth = resolve;
    }));

    render(<IntegrationsView />);
    fireEvent.click(await screen.findByRole("button", { name: "Open Tickets details" }));
    fireEvent.click(screen.getByRole("button", { name: "Check it now" }));

    await waitFor(() => expect(api.integrationConnectionHealth).toHaveBeenCalledWith("conn-1"));
    expect((screen.getByRole("button", { name: "Revoke" }) as HTMLButtonElement).disabled).toBe(true);
    expect(api.disconnectIntegration).not.toHaveBeenCalled();

    resolveHealth({ connection: ticketConnection });
    await waitFor(() => expect(
      (screen.getByRole("button", { name: "Revoke" }) as HTMLButtonElement).disabled,
    ).toBe(false));
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
