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
// A stub call control: placement rule 3 is about where the Stage sits for the
// life of a call, not about realtime media, so the stub only raises the
// call-active signal the way the real control does.
vi.mock("../src/components/VoiceCall", () => ({
  VoiceCall: ({ onCallActive }: { onCallActive?(active: boolean): void }) => (
    <button onClick={() => onCallActive?.(true)} type="button">Start test call</button>
  ),
}));

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
  it("greets a fresh chat with one centred hero Stage and a clean header", async () => {
    renderChat(null);

    expect(screen.getByRole("heading", { level: 2, name: "What should we get done?" }))
      .toBeTruthy();
    // Placement rule 1: the hero orb is the presence - one Stage, centred in
    // the welcome, and no familiar of any kind in the chat header.
    await waitFor(() => {
      const stages = document.querySelectorAll(".familiar-stage");
      expect(stages.length).toBe(1);
      expect(stages[0]!.classList.contains("hero")).toBeTruthy();
      expect(stages[0]!.closest(".welcome")).toBeTruthy();
    });
    expect(document.querySelector(".chat-header .familiar-stage")).toBeNull();
    expect(document.querySelector(".chat-header .familiar-orb")).toBeNull();
    expect(screen.getByRole("heading", { level: 1, name: "New chat" })).toBeTruthy();
  });

  it("moves the one Stage to the newest assistant turn's avatar bullet", async () => {
    api.conversation.mockResolvedValue({
      messages: [
        { id: "m1", role: "user", content: "First ask" },
        { id: "m2", role: "assistant", content: "Older answer" },
        { id: "m3", role: "user", content: "Second ask" },
        { id: "m4", role: "assistant", content: "Newest answer" },
      ],
      active_run_id: null,
    });
    renderChat("conversation-a");

    // Placement rule 2: the newest assistant turn's avatar slot holds the one
    // Stage; every older assistant turn keeps its static badge; the header
    // holds neither.
    await waitFor(() => {
      const stages = document.querySelectorAll(".familiar-stage");
      expect(stages.length).toBe(1);
      const article = stages[0]!.closest("article.message.assistant");
      expect(article?.textContent?.includes("Newest answer")).toBeTruthy();
      expect(stages[0]!.closest(".message-author")).toBeTruthy();
    });
    const older = [...document.querySelectorAll("article.message.assistant")]
      .find((article) => article.textContent?.includes("Older answer"));
    expect(older?.querySelector(".familiar-orb")).toBeTruthy();
    expect(older?.querySelector(".familiar-stage")).toBeNull();
    expect(document.querySelector(".chat-header .familiar-stage")).toBeNull();
  });

  it("returns the one Stage to the centre for the life of a voice call", async () => {
    api.conversation.mockResolvedValue({
      messages: [
        { id: "m1", role: "user", content: "First ask" },
        { id: "m2", role: "assistant", content: "Newest answer" },
      ],
      active_run_id: null,
    });
    renderChat("conversation-a");
    await screen.findByText("Newest answer");

    fireEvent.click(screen.getByRole("button", { name: "Start test call" }));

    // Placement rule 3: centred and large while the call lives; the newest
    // turn falls back to a static badge so there is still exactly one Stage.
    await waitFor(() => {
      const stages = document.querySelectorAll(".familiar-stage");
      expect(stages.length).toBe(1);
      expect(stages[0]!.closest(".voice-stage")).toBeTruthy();
      expect(stages[0]!.classList.contains("voice")).toBeTruthy();
    });
    const newest = [...document.querySelectorAll("article.message.assistant")]
      .find((article) => article.textContent?.includes("Newest answer"));
    expect(newest?.querySelector(".familiar-orb")).toBeTruthy();
    expect(newest?.querySelector(".familiar-stage")).toBeNull();
  });

  it("keeps the one task-details trigger mounted on the phone surface", async () => {
    // The trigger sits above the mobile/console swap so a breakpoint flip
    // never detaches it mid-measure; on the phone it must coexist with the
    // MobileChat surface and still control the sheet.
    vi.stubGlobal("matchMedia", vi.fn().mockImplementation((query: string) => ({
      matches: query === "(max-width: 1020px)" || query === "(max-width: 640px)",
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));
    try {
      renderChat(null);
      expect(document.querySelector(".mobile-surface")).toBeTruthy();
      const trigger = screen.getByRole("button", { name: "Task details" });
      expect(trigger.getAttribute("aria-controls")).toBe("worker-task-details");
      fireEvent.click(trigger);
      expect(await screen.findByRole("dialog", { name: "Task details" })).toBeTruthy();
    } finally {
      vi.unstubAllGlobals();
    }
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
