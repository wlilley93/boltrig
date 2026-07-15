import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { ApiError } from "@/api/client";
import type { WorkItem } from "@/api/types";
import { KanbanPanel } from "@/panels/KanbanPanel";
import { WorkDetail } from "@/panels/workBoard/WorkDetail";
import { buildWorkForest, filterWorkItems } from "@/panels/workBoard/model";
import { clearApiMocks, mockApi } from "../helpers";

const ITEMS: WorkItem[] = [
  {
    id: "goal-1",
    intent: "Launch the service",
    status: "in_flight",
    owner_member: "platform",
    source: "chat",
    convergent: true,
    hatchet_run_id: "run-goal",
  },
  {
    id: "task-1",
    intent: "Verify production readiness",
    status: "awaiting_human",
    owner_member: "ops",
    source: "workflow",
    parent_id: "goal-1",
    convergent: false,
  },
  {
    id: "task-2",
    intent: "Publish release artifacts",
    status: "done",
    owner_member: null,
    source: "workflow",
    parent_id: "goal-1",
    convergent: true,
  },
];

afterEach(() => {
  cleanup();
  clearApiMocks();
  window.location.hash = "";
});

describe("work-board model", () => {
  it("builds parent-child structure and applies every scoped filter", () => {
    const forest = buildWorkForest(ITEMS);
    expect(forest).toHaveLength(1);
    expect(forest[0]?.item.id).toBe("goal-1");
    expect(forest[0]?.children.map((node) => node.item.id)).toEqual(["task-2", "task-1"]);

    const filtered = filterWorkItems(ITEMS, {
      query: "production",
      status: "awaiting_human",
      owner: "owner:ops",
      source: "source:workflow",
      convergent: "no",
    });
    expect(filtered.map((item) => item.id)).toEqual(["task-1"]);
  });
});

describe("KanbanPanel", () => {
  it("renders truthful board records, filters them, and exposes project hierarchy", async () => {
    mockApi({ work: { items: ITEMS, limit: 100, next_cursor: null } });
    render(<KanbanPanel />);

    await screen.findByText("Launch the service");
    expect(screen.getByText("3 of 3")).toBeTruthy();
    expect(screen.getAllByText("Convergent goal")).toHaveLength(2);

    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "production" } });
    expect(screen.getByText("Verify production readiness")).toBeTruthy();
    expect(screen.queryByText("Launch the service")).toBeNull();

    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Project" }));
    const project = screen.getByLabelText("Project view");
    expect(within(project).getByText("2 children")).toBeTruthy();
    fireEvent.click(within(project).getByRole("button", { name: "Collapse Launch the service" }));
    expect(within(project).queryByText("Verify production readiness")).toBeNull();
  });

  it("uses the server status filter and deep-links work items", async () => {
    mockApi({ work: { items: ITEMS, limit: 100, next_cursor: null } });
    render(<KanbanPanel />);
    await screen.findByText("Launch the service");

    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "done" } });
    await waitFor(() => expect(screen.queryByText("Launch the service")).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: /Publish release artifacts/ }));
    expect(window.location.hash).toContain("/kanban/task-2");
  });
});

describe("WorkDetail", () => {
  it("shows scoped context, child navigation, run link, and capped audit history", async () => {
    mockApi({
      workDetail: {
        item: { ...ITEMS[0], on_behalf_of: "will" },
        children: [ITEMS[1]],
        audit: [{
          ts: "2026-07-15T10:00:00Z",
          actor: "ops.agent",
          actor_tier: "member",
          noun: "ticket",
          verb: "update",
          status: "ok",
          detail: { changed: true },
        }],
      },
    });
    render(<WorkDetail itemId="goal-1" />);

    await screen.findByText("Launch the service");
    expect(screen.getByText("will")).toBeTruthy();
    expect(screen.getByText("Newest last · capped at 200 events")).toBeTruthy();
    expect(screen.getByText("ticket.update")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Verify production readiness/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: "run-goal" })).toBeTruthy();
  });

  it("uses the non-enumerating not-found message", async () => {
    mockApi({ workDetail: Promise.reject(new ApiError(404, "not found", { error: "not_found" })) });
    render(<WorkDetail itemId="hidden" />);
    expect(await screen.findByText("Work item not found or not in your visibility scope.")).toBeTruthy();
  });
});
