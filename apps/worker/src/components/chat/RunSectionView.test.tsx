// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BoltrigApiError, type RunTopologyNode } from "@wlilley93/boltrig-web-sdk";

const api = vi.hoisted(() => ({
  runTopology: vi.fn(),
  auditTree: vi.fn(),
}));

vi.mock("../../client", () => ({ client: api }));

import { RunSectionView } from "./RunSectionView";

afterEach(cleanup);

// A head agent with three delegated steps: one finished (and itself delegating
// to two helpers), one waiting on a human, one failed. This is the smallest
// topology that exercises every status tone plus the helper row.
const TOPOLOGY: RunTopologyNode = {
  run_id: "run-1",
  work_item: "wi-root",
  member: "revenue-ops",
  task: "Renewal outreach, top 20 accounts",
  status: "in_flight",
  depth: 0,
  attempts: 1,
  degraded: false,
  children: [
    {
      run_id: "run-2",
      work_item: "wi-read",
      member: "researcher-pool",
      task: "Read health signals",
      status: "done",
      depth: 1,
      attempts: 1,
      degraded: false,
      children: [
        { run_id: "run-4", work_item: "wi-a", task: "Account A", status: "done", depth: 2, attempts: 1, degraded: false, children: [] },
        { run_id: "run-5", work_item: "wi-b", task: "Account B", status: "done", depth: 2, attempts: 1, degraded: false, children: [] },
      ],
    },
    {
      run_id: "run-3",
      work_item: "wi-tickets",
      member: "guardian-pool",
      task: "Raise 3 tickets",
      status: "awaiting_human",
      depth: 1,
      attempts: 1,
      degraded: false,
      children: [],
    },
    {
      run_id: "run-6",
      work_item: "wi-summary",
      task: "Summarise what changed",
      status: "failed",
      depth: 1,
      attempts: 2,
      degraded: true,
      children: [],
    },
  ],
};

function renderSection(overrides: Partial<Parameters<typeof RunSectionView>[0]> = {}) {
  const onBack = vi.fn();
  const view = render(
    <RunSectionView
      runId="run-1"
      title="Renewal outreach, top 20 accounts"
      onBack={onBack}
      {...overrides}
    />,
  );
  return { view, onBack };
}

beforeEach(() => {
  api.runTopology.mockReset();
  api.auditTree.mockReset();
  api.runTopology.mockResolvedValue({ root: TOPOLOGY });
  api.auditTree.mockResolvedValue({
    root: {
      run_id: "run-1",
      children: [
        { run_id: "run-2", actions: 4, tokens: 900, total_cost_micros: 310_000 },
      ],
    },
  });
});

describe("run section view", () => {
  it("draws one column per delegated step with status on the top edge", async () => {
    const { view } = renderSection();
    await waitFor(() => {
      expect(view.container.querySelectorAll(".runsection-col")).toHaveLength(3);
    });
    const bores = view.container.querySelectorAll(".runsection-bore");
    expect(bores[0].getAttribute("data-tone")).toBe("green");
    expect(bores[1].getAttribute("data-tone")).toBe("amber");
    expect(bores[2].getAttribute("data-tone")).toBe("red");
  });

  it("gates only the step that is waiting on a human", async () => {
    const { view } = renderSection();
    await waitFor(() => {
      expect(screen.getAllByText("held")).toHaveLength(1);
    });
    expect(screen.getByText("waiting for you")).toBeTruthy();
    expect(view.container.querySelectorAll(".runsection-gate")).toHaveLength(1);
  });

  it("draws helper sub-bores from the step's real children", async () => {
    const { view } = renderSection();
    await waitFor(() => {
      expect(screen.getByText("2 helpers")).toBeTruthy();
    });
    expect(view.container.querySelectorAll(".runsection-worker")).toHaveLength(2);
  });

  it("never draws the design's invented durability register", async () => {
    renderSection();
    await waitFor(() => {
      expect(api.runTopology).toHaveBeenCalledWith("run-1");
    });
    // RunTopologyNode has no durable field, so the dashed "not held in place"
    // rail must not exist in any form.
    expect(screen.queryByText(/not held in place/)).toBeNull();
  });

  it("annotates steps only with real fields: attempts, degraded, audit cost", async () => {
    renderSection();
    await waitFor(() => {
      expect(screen.getByText("2 attempts")).toBeTruthy();
    });
    expect(screen.getByText("degraded result")).toBeTruthy();
    // Digits only: the currency symbol placement is locale-dependent.
    expect(screen.getByText(/4 actions · .*0\.31/)).toBeTruthy();
  });

  it("keeps both subtitle registers derived from the same topology", async () => {
    const { view } = renderSection();
    await waitFor(() => {
      expect(screen.getByText("3 delegated steps, 1 of them delegated further")).toBeTruthy();
    });
    view.unmount();
    renderSection({ devDetails: true });
    await waitFor(() => {
      expect(screen.getByText("run-1 · 3 steps · depth 2")).toBeTruthy();
    });
  });

  it("names the head agent in the legend from the topology member", async () => {
    renderSection();
    await waitFor(() => {
      expect(screen.getByText("revenue-ops")).toBeTruthy();
    });
  });

  it("returns to the conversation through the caller", async () => {
    const { onBack } = renderSection();
    fireEvent.click(screen.getByRole("button", { name: "Back to the conversation" }));
    expect(onBack).toHaveBeenCalled();
    // Let the in-flight topology fetch settle inside the test's lifetime.
    await waitFor(() => expect(api.runTopology).toHaveBeenCalled());
  });

  it("says so honestly when the run delegated nothing", async () => {
    api.runTopology.mockResolvedValue({ root: { ...TOPOLOGY, children: [] } });
    renderSection();
    await waitFor(() => {
      expect(screen.getByText(/nothing was delegated/)).toBeTruthy();
    });
  });

  it("survives an audit-tree failure because the annotation is optional", async () => {
    api.auditTree.mockRejectedValue(new Error("down"));
    const { view } = renderSection();
    await waitFor(() => {
      expect(view.container.querySelectorAll(".runsection-col")).toHaveLength(3);
    });
    expect(screen.queryByText(/actions ·/)).toBeNull();
  });

  it("distinguishes denial from absence when topology cannot load", async () => {
    api.runTopology.mockRejectedValue(new BoltrigApiError(403, {}));
    renderSection();
    await waitFor(() => {
      expect(screen.getByText(/cannot view this run/)).toBeTruthy();
    });
  });
});
