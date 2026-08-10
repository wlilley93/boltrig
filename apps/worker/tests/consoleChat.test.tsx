// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  artifacts: vi.fn(),
  chatConfig: vi.fn(),
  conversation: vi.fn(),
  conversations: vi.fn(),
  modelProfiles: vi.fn(),
  streamChat: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { ChatView } from "../src/components/ChatView";

beforeEach(() => {
  document.documentElement.dataset.theme = "dark";
  api.artifacts.mockResolvedValue({ artifacts: [], next_cursor: null });
  api.chatConfig.mockResolvedValue({
    attachments: {
      max_count: 8,
      max_bytes: 262_144,
      max_total_bytes: 1_048_576,
      model_readable_media_types: ["text/*"],
    },
  });
  api.conversations.mockResolvedValue({
    conversations: [{
      id: "conversation-a",
      title: "Renewal outreach",
      status: "active",
      updated_at: "2026-01-01T00:00:00Z",
    }],
  });
  api.modelProfiles.mockResolvedValue({ profiles: [] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  delete document.documentElement.dataset.theme;
  try {
    localStorage.removeItem("boltrig-worker-theme");
  } catch {
    // Storage is optional in this environment.
  }
});

function renderChat(conversationId: string | null) {
  render(
    <ChatView
      conversationId={conversationId}
      onConversation={vi.fn()}
      onChanged={vi.fn()}
    />,
  );
}

describe("console chat surface", () => {
  it("greets a fresh chat with the console hero and one Familiar Stage", async () => {
    renderChat(null);

    expect(screen.getByRole("heading", { level: 2, name: "What needs doing?" }))
      .toBeTruthy();
    // ADR 0025: exactly one Stage session per client. In hero mode the Stage
    // lives in the welcome; the header slot holds only the cheap badge.
    await waitFor(() => {
      const stages = document.querySelectorAll(".familiar-stage");
      expect(stages.length).toBe(1);
      expect(stages[0]!.classList.contains("hero")).toBeTruthy();
    });
    expect(screen.getByRole("heading", { level: 1, name: "New chat" })).toBeTruthy();
  });

  it("titles the header with the real conversation, not a slogan", async () => {
    api.conversation.mockResolvedValue({ messages: [], active_run_id: null });
    renderChat("conversation-a");

    expect(await screen.findByRole("heading", { level: 1, name: "Renewal outreach" }))
      .toBeTruthy();
  });

  it("flips the theme from the header and persists the choice", () => {
    renderChat(null);

    fireEvent.click(screen.getByRole("button", { name: "Toggle theme" }));
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem("boltrig-worker-theme")).toBe("light");

    fireEvent.click(screen.getByRole("button", { name: "Toggle theme" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});
