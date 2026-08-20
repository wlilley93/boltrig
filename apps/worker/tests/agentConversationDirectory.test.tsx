// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  deleteMyConversation: vi.fn(),
  moveConversationProject: vi.fn(),
  namedAgents: vi.fn(),
  switchActiveContext: vi.fn(),
  workspaces: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { TaskList } from "../src/components/shell/TaskList";
import { consumePendingChatAgent } from "../src/components/chat/pendingChatTarget";

const conversations = [
  {
    id: "conversation-cos",
    title: "Plan the launch",
    status: "active",
    updated_at: "2026-08-20T12:00:00Z",
    agent_address: "chief-of-staff",
    workspace_id: null,
  },
  {
    id: "conversation-legal",
    title: "Review the terms",
    status: "active",
    updated_at: "2026-08-20T11:00:00Z",
    agent_address: "head-of-legal",
    workspace_id: null,
  },
];

function renderDirectory(overrides: Record<string, unknown> = {}) {
  const props = {
    conversations,
    conversationStatus: "ready" as const,
    selectedConversation: null,
    workingConversationIds: [],
    onConversation: vi.fn(),
    onNewConversation: vi.fn(),
    onConversationArchived: vi.fn(),
    onLoadMore: vi.fn(),
    onRetryConversations: vi.fn(),
    hasMoreConversations: false,
    ...overrides,
  };
  render(<TaskList {...props} />);
  return props;
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  api.namedAgents.mockResolvedValue({
    named_agents: [
      { address: "chief-of-staff", name: "Chief of Staff", enabled: true,
        default_for_intake: true },
      { address: "head-of-legal", name: "Head of Legal", enabled: true,
        default_for_intake: false },
      { address: "retired", name: "Retired Agent", enabled: false,
        default_for_intake: false },
    ],
  });
  api.workspaces.mockResolvedValue({
    workspaces: [{ id: "project-alpha", name: "Project Alpha", status: "active" }],
  });
  api.switchActiveContext.mockResolvedValue({ status: "ok" });
  api.moveConversationProject.mockResolvedValue({ status: "ok" });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  localStorage.clear();
  sessionStorage.clear();
});

describe("agent and project conversation projections", () => {
  it("opens the latest chat from a collapsible agent pile and starts a targeted chat", async () => {
    const props = renderDirectory();
    fireEvent.click(screen.getByRole("radio", { name: /By agent/ }));

    const legal = await screen.findByRole("button", { name: "Head of Legal" });
    expect(screen.queryByText("Retired Agent")).toBeNull();
    fireEvent.click(legal);
    await waitFor(() => expect(props.onConversation).toHaveBeenCalledWith("conversation-legal"));

    fireEvent.click(screen.getByRole("button", { name: "New chat with Head of Legal" }));
    await waitFor(() => expect(props.onNewConversation).toHaveBeenCalledOnce());
    expect(consumePendingChatAgent()).toBe("head-of-legal");
  });

  it("moves a chat into a user project with compare-and-swap provenance", async () => {
    const props = renderDirectory();
    fireEvent.click(screen.getByRole("radio", { name: /By project/ }));

    expect(await screen.findByText("Project Alpha")).toBeTruthy();
    const project = document.querySelector('[data-group-id="project:project-alpha"]');
    expect(project).toBeTruthy();
    fireEvent.drop(project!, {
      dataTransfer: { getData: () => "conversation-legal" },
    });
    await waitFor(() => expect(api.moveConversationProject).toHaveBeenCalledWith(
      "conversation-legal", "project-alpha", null,
    ));
    expect(props.onRetryConversations).toHaveBeenCalledOnce();

    fireEvent.click(screen.getByRole("button", { name: "New chat in Project Alpha" }));
    await waitFor(() => expect(api.switchActiveContext).toHaveBeenCalledWith("project-alpha"));
    expect(props.onNewConversation).toHaveBeenCalledOnce();
  });
});
