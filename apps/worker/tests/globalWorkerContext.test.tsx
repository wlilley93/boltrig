// @vitest-environment happy-dom

import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
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
  localStorage.clear();
  document.documentElement.removeAttribute("data-character");
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.location.hash = "";
  localStorage.clear();
});

describe("global Worker identity context", () => {
  it("applies the authoritative character during an existing identity refresh", async () => {
    api.meSettings.mockResolvedValue({
      profile,
      settings: { "agent.character": "jarvis" },
    });
    render(
      <WorkerGlobalContextProvider>
        <Topbar title="Runs" />
      </WorkerGlobalContextProvider>,
    );

    expect(await screen.findByText("Alice")).toBeTruthy();
    expect(screen.queryByText("Acme / Operations")).toBeNull();
    expect(document.documentElement.dataset.character).toBe("jarvis");
    expect(api.meSettings).toHaveBeenCalledTimes(1);
  });

  it("shows the user without a redundant organisation or workspace label", async () => {
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
    expect(within(topbar).queryByText("Acme / Operations")).toBeNull();
    expect(within(topbar).queryByText(/pending/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /Inbox/i })).toBeNull();
  });

  it("refreshes context without adding a visible workspace label", async () => {
    api.consoleOverview
      .mockResolvedValueOnce({ workspace_id: "workspace-a" })
      .mockResolvedValueOnce({ workspace_id: "workspace-b" });
    render(
      <WorkerGlobalContextProvider>
        <Topbar title="Account" />
      </WorkerGlobalContextProvider>,
    );

    expect(await screen.findByText("Alice")).toBeTruthy();
    expect(screen.queryByText("Acme / Operations")).toBeNull();
    notifyWorkerContextChanged();

    await waitFor(() => expect(api.consoleOverview).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("Acme / Research")).toBeNull();
    expect(api.hitl).not.toHaveBeenCalled();
  });

  it("does not poll a global approval queue", async () => {
    api.consoleOverview.mockResolvedValue({ workspace_id: null });
    api.hitl.mockRejectedValue(new Error("offline"));

    render(
      <WorkerGlobalContextProvider>
        <Topbar title="Home" />
      </WorkerGlobalContextProvider>,
    );

    expect(await screen.findByText("Alice")).toBeTruthy();
    expect(screen.queryByText("Acme / Organisation-wide")).toBeNull();
    expect(api.hitl).not.toHaveBeenCalled();
  });
});
