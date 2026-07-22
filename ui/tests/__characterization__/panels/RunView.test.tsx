import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";

const routerMocks = vi.hoisted(() => ({
  closeRun: vi.fn(),
  navigate: vi.fn(),
  openRun: vi.fn(),
  runId: "run-parent" as string | undefined,
}));

const streamMock = vi.hoisted(() => ({ current: undefined as unknown }));

vi.mock("@/router", () => ({
  closeRun: routerMocks.closeRun,
  navigate: routerMocks.navigate,
  openRun: routerMocks.openRun,
  useRoute: () => ({ tab: "chat", segs: ["chat"], runId: routerMocks.runId }),
}));

vi.mock("@/panels/runView/useRunStream", () => ({
  useRunStream: () => streamMock.current,
}));

import { api, ApiError } from "@/api/client";
import type { AuditTreeResponse, ChatEvent } from "@/api/types";
import { normalizeEvents } from "@/panels/chatTurn";
import { nextRunTrail, RunDrawer } from "@/panels/RunView";
import { RunInspector } from "@/panels/runView/RunInspector";
import { RunTabs, type RunTabId } from "@/panels/runView/RunTabs";
import type { RunStream } from "@/panels/runView/useRunStream";
import { clearApiMocks, mockApi } from "../helpers";

const TREE: AuditTreeResponse = {
  root: {
    run_id: "run-parent",
    actor: "bolt",
    tier: "tier1",
    depth: 1,
    actions: 3,
    tokens: 1200,
    total_cost_micros: 125000,
    statuses: { ok: 2, paused: 1 },
    children: [{ run_id: "run-child", actor: "worker", statuses: { ok: 1 } }],
  },
};

const EVENTS = [
  { type: "message_start", run_id: "run-parent", conversation_id: "conv-1" },
  {
    type: "tool_call",
    call_id: "call-1",
    verb: "ticket.search",
    input: { query: "open" },
  },
  {
    type: "tool_result",
    call_id: "call-1",
    verb: "ticket.search",
    status: "ok",
    output: { count: 2 },
  },
  {
    type: "subagent",
    child_run_id: "run-child",
    task: "Review the matching tickets",
    skills: ["ticket/read"],
    name: "Reviewer",
  },
  {
    type: "hitl",
    hitl_request_id: "hitl-1",
    kind: "approval",
    question: "Approve the outbound update?",
    options: ["approve", "reject"],
  },
  { type: "text_delta", delta: "Run finished." },
  { type: "message_end", run_id: "run-parent" },
] as unknown as ChatEvent[];

function makeStream(events: ChatEvent[] = EVENTS): RunStream {
  return {
    events,
    streamError: null,
    resolvedHitls: {},
    settled: true,
    replayIdx: null,
    setReplayIdx: vi.fn(),
    canReplay: events.length > 1,
    shownEvents: events,
    turn: normalizeEvents(events),
    resolveHitl: vi.fn(),
  };
}

beforeEach(() => {
  routerMocks.closeRun.mockReset();
  routerMocks.navigate.mockReset();
  routerMocks.openRun.mockReset();
  routerMocks.runId = "run-parent";
  streamMock.current = makeStream();
});

afterEach(() => {
  cleanup();
  clearApiMocks();
});

describe("RunInspector", () => {
  it("shows real summary data and event-backed tabs", () => {
    render(
      <RunInspector
        tree={{ data: TREE, loading: false, error: null }}
        stream={makeStream()}
      />,
    );

    expect(screen.getByRole("heading", { name: "Run overview" })).toBeTruthy();
    expect(screen.getByTitle("125000 micros").textContent).toBe("0.125");
    expect(screen.getByRole("tab", { name: /Tool calls/ })).toBeTruthy();
    expect(screen.getByRole("tab", { name: /Approvals/ })).toBeTruthy();

    fireEvent.click(screen.getByRole("tab", { name: /Tool calls/ }));
    expect(screen.getByText("Ticket search")).toBeTruthy();

    fireEvent.click(screen.getByRole("tab", { name: /Approvals/ }));
    expect(screen.getByText("Approve the outbound update?")).toBeTruthy();

    fireEvent.click(screen.getByRole("tab", { name: "Raw" }));
    expect(screen.getByText(/"run_id": "run-parent"/)).toBeTruthy();
  });

  it("omits event-specific tabs when the run has no matching events", () => {
    const events = [
      { type: "message_start", run_id: "run-empty" },
      { type: "text_delta", delta: "No calls." },
    ] as unknown as ChatEvent[];
    render(
      <RunInspector
        tree={{ data: TREE, loading: false, error: null }}
        stream={makeStream(events)}
      />,
    );

    expect(screen.queryByRole("tab", { name: /Tool calls/ })).toBeNull();
    expect(screen.queryByRole("tab", { name: /Approvals/ })).toBeNull();
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Overview",
      "Timeline",
      "Tree",
      "Raw",
    ]);
  });

  it("keeps child-run navigation in the timeline", () => {
    render(
      <RunInspector
        tree={{ data: TREE, loading: false, error: null }}
        stream={makeStream()}
      />,
    );
    fireEvent.click(screen.getByRole("tab", { name: "Timeline" }));
    fireEvent.click(screen.getByRole("button", { name: "Open run" }));
    expect(routerMocks.openRun).toHaveBeenCalledWith("run-child");
  });

  it("filters the execution tree and opens a real child run", () => {
    render(
      <RunInspector
        tree={{ data: TREE, loading: false, error: null }}
        stream={makeStream()}
      />,
    );
    fireEvent.click(screen.getByRole("tab", { name: "Tree" }));

    const filter = screen.getByRole("searchbox", {
      name: "Filter execution tree",
    });
    fireEvent.change(filter, { target: { value: "worker" } });
    fireEvent.click(screen.getByRole("button", { name: "run-child" }));
    expect(routerMocks.openRun).toHaveBeenCalledWith("run-child");

    fireEvent.change(filter, { target: { value: "not-a-run" } });
    expect(screen.getByText("No runs match this filter.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "run-child" })).toBeNull();
  });

  it("keeps run approvals behind the shared confirmation step", async () => {
    mockApi({ respondHitl: { status: "answered", response_id: "response-1" } });
    render(
      <RunInspector
        tree={{ data: TREE, loading: false, error: null }}
        stream={makeStream()}
      />,
    );

    fireEvent.click(screen.getByRole("tab", { name: /Approvals/ }));
    fireEvent.click(screen.getByRole("button", { name: "approve" }));
    expect(api.respondHitl).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Confirm approve" }));
    await waitFor(() => {
      expect(api.respondHitl).toHaveBeenCalledWith("hitl-1", {
        decision: "approve",
        notes: "",
      });
    });
  });

  it("keeps the live timeline usable when the audit tree is degraded", () => {
    render(
      <RunInspector
        tree={{ data: null, loading: false, error: "audit service unavailable" }}
        stream={makeStream()}
      />,
    );
    expect(screen.getByText("Audit summary: audit service unavailable")).toBeTruthy();

    fireEvent.click(screen.getByRole("tab", { name: "Timeline" }));
    expect(screen.getByText("Run finished.")).toBeTruthy();

    fireEvent.click(screen.getByRole("tab", { name: "Raw" }));
    expect(screen.getByText("Audit tree: audit service unavailable")).toBeTruthy();
  });
});

function KeyboardTabs() {
  const [active, setActive] = useState<RunTabId>("overview");
  return (
    <RunTabs
      tabs={[
        { id: "overview", label: "Overview" },
        { id: "timeline", label: "Timeline" },
        { id: "tree", label: "Tree" },
      ]}
      active={active}
      onChange={setActive}
    />
  );
}

describe("RunTabs", () => {
  it("supports arrow-key tab selection and focus", () => {
    render(<KeyboardTabs />);
    const overview = screen.getByRole("tab", { name: "Overview" });
    overview.focus();
    fireEvent.keyDown(overview, { key: "ArrowRight" });
    const timeline = screen.getByRole("tab", { name: "Timeline" });
    expect(timeline.getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(timeline);
  });
});

describe("RunDrawer", () => {
  it("keeps a reversible ancestry trail when following child runs", async () => {
    mockApi({ auditTree: TREE });
    const selectRun = vi.fn();
    render(
      <RunDrawer
        runId="run-grandchild"
        trail={["run-parent", "run-child", "run-grandchild"]}
        onSelectRun={selectRun}
      />,
    );
    await screen.findByRole("heading", { name: "Run overview" });

    fireEvent.click(screen.getByRole("button", { name: "run-parent" }));
    expect(selectRun).toHaveBeenCalledWith("run-parent");
    expect(screen.getByText("run-grandchild").getAttribute("aria-current")).toBe("page");
  });

  it("appends descendants, truncates to ancestors, and clears on close", () => {
    expect(nextRunTrail(["parent"], "child")).toEqual(["parent", "child"]);
    expect(nextRunTrail(["parent", "child", "grandchild"], "child")).toEqual([
      "parent",
      "child",
    ]);
    expect(nextRunTrail(["parent"], undefined)).toEqual([]);
  });

  it("preserves Escape, backdrop and close-button behavior", async () => {
    mockApi({ auditTree: TREE });
    render(<RunDrawer runId="run-parent" />);
    await screen.findByRole("heading", { name: "Run overview" });

    const palette = document.createElement("div");
    palette.className = "cmdk-overlay";
    document.body.appendChild(palette);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(routerMocks.closeRun).not.toHaveBeenCalled();
    palette.remove();

    fireEvent.keyDown(window, { key: "Escape" });
    fireEvent.click(screen.getByRole("dialog", { name: "Run details" }));
    fireEvent.click(screen.getByRole("button", { name: "Close run inspector" }));
    expect(routerMocks.closeRun).toHaveBeenCalledTimes(3);
  });

  it("cross-links to the real runs and audit surfaces", async () => {
    mockApi({ auditTree: TREE });
    render(<RunDrawer runId="run-parent" />);
    await screen.findByRole("heading", { name: "Run overview" });

    fireEvent.click(screen.getByRole("button", { name: "All runs" }));
    fireEvent.click(screen.getByRole("button", { name: "Audit & costs" }));
    expect(routerMocks.navigate).toHaveBeenNthCalledWith(1, "/runs");
    expect(routerMocks.navigate).toHaveBeenNthCalledWith(2, "/insight");
  });

  it("keeps the scoped not-found state instead of rendering tabs", async () => {
    mockApi();
    vi.mocked(api.auditTree).mockRejectedValue(
      new ApiError(404, "GET /v1/audit/tree/missing-run -> 404", {
        error: "unknown_run",
      }),
    );
    streamMock.current = { ...makeStream([]), streamError: "404 not found" };
    render(<RunDrawer runId="missing-run" />);

    expect(
      await screen.findByText("Run not found, or not in your visibility scope."),
    ).toBeTruthy();
    expect(screen.queryByRole("tablist", { name: "Run inspector sections" })).toBeNull();
  });
});
