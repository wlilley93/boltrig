// @vitest-environment happy-dom

import type { ComponentType } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BoltrigApiError } from "@wlilley93/boltrig-web-sdk";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  agentCapabilities: vi.fn(),
  auditTree: vi.fn(),
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
}));

vi.mock("../src/client", () => ({ client: api }));

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
  const promise = new Promise<T>((accept, decline) => {
    resolve = accept;
    reject = decline;
  });
  return { promise, resolve, reject };
}

const surfaces: Array<{
  name: string;
  View: ComponentType;
  load: ReturnType<typeof vi.fn>;
  empty: unknown;
  loadingTitle: string;
  emptyTitle: string;
  failureTitles: Record<number, string>;
}> = [
  {
    name: "Runs",
    View: RunsView,
    load: api.runs,
    empty: { runs: [], next_cursor: null },
    loadingTitle: "Loading runs",
    emptyTitle: "No runs yet",
    failureTitles: {
      403: "Run access denied",
      404: "Runs not found",
      503: "Runs unavailable",
    },
  },
  {
    name: "Agents",
    View: AgentsView,
    load: api.agentCapabilities,
    empty: { agent_capabilities: [] },
    loadingTitle: "Loading agent profiles",
    emptyTitle: "No agent profiles visible",
    failureTitles: {
      403: "Agent access denied",
      404: "Agent inventory not found",
      503: "Agents unavailable",
    },
  },
  {
    name: "Knowledge",
    View: KnowledgeView,
    load: api.knowledgeAssets,
    empty: { assets: [], next_offset: null },
    loadingTitle: "Loading knowledge",
    emptyTitle: "No source documents",
    failureTitles: {
      403: "Knowledge access denied",
      404: "Knowledge not found",
      503: "Knowledge unavailable",
    },
  },
  {
    name: "Memory",
    View: MemoryView,
    load: api.memoryFacts,
    empty: { facts: [], scopes: [] },
    loadingTitle: "Loading memory",
    emptyTitle: "No memory facts in view",
    failureTitles: {
      403: "Memory access denied",
      404: "Memory not found",
      503: "Memory unavailable",
    },
  },
];

beforeEach(() => {
  api.auditTree.mockResolvedValue({ root: null });
  api.knowledgeProviders.mockResolvedValue({ providers: [] });
  api.runTopology.mockResolvedValue({ root: null });
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

describe.each(surfaces)("$name primary-surface state", ({
  View,
  load,
  empty,
  loadingTitle,
  emptyTitle,
  failureTitles,
}) => {
  it("distinguishes initial loading from a successful empty response", async () => {
    const request = deferred<unknown>();
    load.mockReturnValue(request.promise);

    render(<View />);

    expect(screen.getByRole("heading", { name: loadingTitle })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: emptyTitle })).toBeNull();

    await act(async () => request.resolve(empty));
    expect(await screen.findByRole("heading", { name: emptyTitle })).toBeTruthy();
  });

  it.each([403, 404, 503])("renders an honest %s failure state", async (status) => {
    load.mockRejectedValue(new BoltrigApiError(status, { reason: "test" }));

    render(<View />);

    expect(await screen.findByRole("heading", {
      name: failureTitles[status],
    })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: emptyTitle })).toBeNull();
  });
});

describe("Worker stale-data and deep-link honesty", () => {
  it("keeps the last authorized run page when a refresh is temporarily unavailable", async () => {
    api.runs
      .mockResolvedValueOnce({
        runs: [{
          run_id: "run-stale",
          work_item: "work-stale",
          intent: "Retained run",
          status: "done",
        }],
        next_cursor: null,
      })
      .mockRejectedValueOnce(new BoltrigApiError(503, {}));

    render(<RunsView />);
    expect(await screen.findByText("Retained run")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));

    expect(await screen.findByText(/Showing the last loaded page/)).toBeTruthy();
    expect(screen.getByText("Retained run")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Runs unavailable" })).toBeNull();
  });

  it("shows an unknown agent deep link as not found instead of the roster", async () => {
    window.location.hash = "#/agents/missing-agent";
    api.agentCapabilities.mockResolvedValue({
      agent_capabilities: [{
        name: "known-agent",
        runtime: "codex",
        supported_skills: [],
        max_depth: 1,
        is_ephemeral: false,
        cost_tier: "standard",
        model_endpoint: null,
        familiar_genotype: null,
        source: "control-plane",
        is_active: true,
        status: "active",
      }],
    });

    render(<AgentsView />);

    expect(await screen.findByRole("heading", {
      name: "Agent profile not found",
    })).toBeTruthy();
    expect(screen.queryByText("known-agent")).toBeNull();
  });
});

describe("Worker exact-detail response ordering", () => {
  it("never renders Work A after the user has selected Work B", async () => {
    const detailA = deferred<unknown>();
    const detailB = deferred<unknown>();
    api.work.mockResolvedValue({
      items: [
        { id: "work-a", intent: "Work A", status: "pending" },
        { id: "work-b", intent: "Work B", status: "pending" },
      ],
      next_cursor: null,
    });
    api.workDetail.mockImplementation((id: string) => (
      id === "work-a" ? detailA.promise : detailB.promise
    ));

    render(<WorkView />);
    fireEvent.click(await screen.findByRole("button", { name: /Work A/ }));
    await waitFor(() => expect(api.workDetail).toHaveBeenCalledWith("work-a"));
    fireEvent.click(screen.getByRole("button", { name: /Work B/ }));
    await waitFor(() => expect(api.workDetail).toHaveBeenCalledWith("work-b"));

    await act(async () => detailB.resolve({
      item: { id: "work-b", intent: "Detail B", status: "pending" },
      children: [],
      audit: [],
    }));
    expect(await screen.findByRole("heading", { name: "Detail B" })).toBeTruthy();

    await act(async () => detailA.resolve({
      item: { id: "work-a", intent: "Detail A", status: "pending" },
      children: [],
      audit: [],
    }));
    expect(screen.getByRole("heading", { name: "Detail B" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Detail A" })).toBeNull();
  });

  it("never renders Knowledge A after the user has selected Knowledge B", async () => {
    const detailA = deferred<unknown>();
    const detailB = deferred<unknown>();
    const assetA = {
      id: "asset-a",
      title: "Source A",
      filename: "a.pdf",
      segment_count: 1,
      revision_id: "revision-a",
      source_kind: "upload",
      source_ref: null,
    };
    const assetB = {
      ...assetA,
      id: "asset-b",
      title: "Source B",
      filename: "b.pdf",
      revision_id: "revision-b",
    };
    api.knowledgeAssets.mockResolvedValue({
      assets: [assetA, assetB],
      next_offset: null,
    });
    api.knowledgeAsset.mockImplementation((id: string) => (
      id === "asset-a" ? detailA.promise : detailB.promise
    ));

    render(<KnowledgeView />);
    const inspect = await screen.findAllByRole("button", { name: "Inspect" });
    fireEvent.click(inspect[0]);
    await waitFor(() => expect(api.knowledgeAsset).toHaveBeenCalledWith("asset-a"));
    fireEvent.click(inspect[1]);
    await waitFor(() => expect(api.knowledgeAsset).toHaveBeenCalledWith("asset-b"));

    await act(async () => detailB.resolve({
      asset: { ...assetB, title: "Detail B" },
      segments: [],
      projections: [],
      provenance: {},
    }));
    expect(await screen.findByRole("heading", {
      level: 2,
      name: "Detail B",
    })).toBeTruthy();

    await act(async () => detailA.resolve({
      asset: { ...assetA, title: "Detail A" },
      segments: [],
      projections: [],
      provenance: {},
    }));
    expect(screen.getByRole("heading", { level: 2, name: "Detail B" })).toBeTruthy();
    expect(screen.queryByRole("heading", { level: 2, name: "Detail A" })).toBeNull();
  });
});
