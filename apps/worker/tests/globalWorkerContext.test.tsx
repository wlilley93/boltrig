// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  consoleOverview: vi.fn(),
  currentOrg: vi.fn(),
  hitl: vi.fn(),
  meSettings: vi.fn(),
  searchConversations: vi.fn(),
  workspaces: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { Sidebar, Topbar } from "../src/components/Shell";
import {
  notifyWorkerContextChanged,
  WorkerGlobalContextProvider,
} from "../src/components/WorkerGlobalContext";

const profile = {
  id: "alice",
  email: "alice@example.test",
  display_name: "Alice",
  role: "admin",
};

const workspaces = [
  {
    id: "workspace-a",
    name: "Operations",
    slug: "operations",
    status: "active",
    settings: {},
  },
  {
    id: "workspace-b",
    name: "Research",
    slug: "research",
    status: "active",
    settings: {},
  },
];

beforeEach(() => {
  api.meSettings.mockResolvedValue({ profile, settings: {} });
  api.currentOrg.mockResolvedValue({
    organisation: {
      id: "org-a",
      name: "Acme",
      slug: "acme",
      settings: {},
      allow_own_ai_keys: false,
      require_two_factor: false,
    },
  });
  api.workspaces.mockResolvedValue({ workspaces });
  api.consoleOverview.mockResolvedValue({
    workspace_id: "workspace-a",
  });
  api.hitl.mockResolvedValue({
    requests: [
      { id: "approval-a", type: "approval", question: "Approve transfer?" },
      { id: "question-a", type: "question", question: "Which contract?" },
    ],
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.location.hash = "";
});

describe("global Worker identity and decision context", () => {
  it("shows user, organisation, active workspace, and pending decisions globally", async () => {
    render(
      <WorkerGlobalContextProvider>
        <Topbar title="Runs" status="12 visible" />
        <Sidebar
          route="runs"
          conversations={[]}
          selectedConversation={null}
          onRoute={vi.fn()}
          onConversation={vi.fn()}
          onConversationRestored={vi.fn()}
          onLoadMore={vi.fn()}
          hasMoreConversations={false}
        />
      </WorkerGlobalContextProvider>,
    );

    const topbar = screen.getByRole("banner");
    expect(await within(topbar).findByText("Alice")).toBeTruthy();
    expect(within(topbar).getByText("Acme / Operations")).toBeTruthy();
    expect(within(topbar).getByText("2 pending")).toBeTruthy();
    // The decided target has no Inbox nav row, so the count that used to ride on
    // it now states itself on the sidebar's status line. Same signal, same label.
    expect(screen.getByLabelText("2 pending decisions").textContent)
      .toBe("2 things need you");

    fireEvent.click(within(topbar).getByRole("button", {
      name: "Open Inbox, 2 pending decisions",
    }));
    expect(window.location.hash).toBe("#/inbox");
  });

  it("refreshes the visible active workspace after a context switch", async () => {
    api.consoleOverview
      .mockResolvedValueOnce({ workspace_id: "workspace-a" })
      .mockResolvedValueOnce({ workspace_id: "workspace-b" });
    api.hitl
      .mockResolvedValueOnce({
        requests: [{ id: "approval-a", type: "approval", question: "Approve transfer?" }],
      })
      .mockResolvedValueOnce({ requests: [] });

    render(
      <WorkerGlobalContextProvider>
        <Topbar title="Account" />
      </WorkerGlobalContextProvider>,
    );

    expect(await screen.findByText("Acme / Operations")).toBeTruthy();
    expect(screen.getByText("1 pending")).toBeTruthy();
    notifyWorkerContextChanged();

    expect(await screen.findByText("Acme / Research")).toBeTruthy();
    expect(await screen.findByText("Inbox clear")).toBeTruthy();
    await waitFor(() => expect(api.consoleOverview).toHaveBeenCalledTimes(2));
    expect(api.hitl).toHaveBeenCalledTimes(2);
  });

  it("reports unavailable pending status instead of claiming the Inbox is clear", async () => {
    api.consoleOverview.mockResolvedValue({ workspace_id: null });
    api.hitl.mockRejectedValue(new Error("offline"));

    render(
      <WorkerGlobalContextProvider>
        <Topbar title="Home" />
      </WorkerGlobalContextProvider>,
    );

    expect(await screen.findByText("Acme / Organisation-wide")).toBeTruthy();
    expect(await screen.findByText("Inbox unavailable")).toBeTruthy();
    expect(screen.queryByText("Inbox clear")).toBeNull();
  });
});
