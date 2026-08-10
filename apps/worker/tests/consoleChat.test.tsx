// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  artifacts: vi.fn(),
  chatConfig: vi.fn(),
  conversation: vi.fn(),
  conversations: vi.fn(),
  createCall: vi.fn(),
  modelProfiles: vi.fn(),
  streamChat: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));
// A stub call control: placement rule 3 is about where the Stage sits for the
// life of a call, not about realtime media, so the stub only raises the
// call-active signal the way the real control does. It keeps the real idle
// markup shape (.voice-idle > .secondary-button) because the empty-draft
// primary starts the call through that button.
vi.mock("../src/components/VoiceCall", () => ({
  VoiceCall: ({ onCallActive }: { onCallActive?(active: boolean): void }) => (
    <div className="voice-idle">
      <button
        className="secondary-button"
        onClick={() => onCallActive?.(true)}
        type="button"
      >Start test call</button>
    </div>
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
    localStorage.removeItem("boltrig-worker-voice-banner-dismissed");
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
  it("greets a fresh chat the way the decided target does, chrome-free", async () => {
    renderChat(null);

    // The decided target opens on a quiet mark, one question and four starters.
    // It does NOT open on the Stage at hero size: ADR 0025 placement rule 1 is
    // superseded here by the target, and the unbounded square it put in the
    // welcome was what pushed the composer off a short window.
    expect(screen.getByRole("heading", { level: 2, name: "What needs doing?" }))
      .toBeTruthy();
    expect(document.querySelectorAll(".welcome .starter-card").length).toBe(4);
    expect(document.querySelectorAll(".welcome .starter-icon").length).toBe(4);
    await waitFor(() => {
      expect(document.querySelector(".welcome .familiar-stage")).toBeNull();
    });
    // The New state draws no header bar at all (so no familiar can sit in
    // one), yet the theme control stays reachable as a floating action.
    expect(document.querySelector(".chat-header")).toBeNull();
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
    expect(screen.getByRole("button", { name: "Toggle theme" })).toBeTruthy();
  });

  it("fills the composer draft from a starter card without sending", () => {
    renderChat(null);

    fireEvent.click(screen.getByRole("button", { name: /Find something out/ }));

    const composer = screen.getByRole("textbox", {
      name: "Task instructions",
    }) as HTMLTextAreaElement;
    expect(composer.value).toBe("Find something out");
    expect(api.streamChat).not.toHaveBeenCalled();
  });

  it("offers the voice banner on the New state and remembers its dismissal", () => {
    renderChat(null);

    expect(screen.getByText("Try boltrig Voice")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss the voice banner" }));
    expect(screen.queryByText("Try boltrig Voice")).toBeNull();
    expect(localStorage.getItem("boltrig-worker-voice-banner-dismissed")).toBe("true");
  });

  it("turns the empty-draft primary into a voice call, and says so", async () => {
    renderChat(null);

    // Empty draft: the primary is voice, with the hint line stating it.
    expect(screen.getByText("Nothing typed, so the round button starts a voice call."))
      .toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Start a voice call" }));

    // The click reaches VoiceCall's own start control, so the call machinery
    // (capability fallbacks, media teardown) stays in one place.
    await waitFor(() => {
      expect(document.querySelector(".voice-stage")).toBeTruthy();
    });

    // A non-empty draft flips the primary back to Send.
    fireEvent.change(screen.getByRole("textbox", { name: "Task instructions" }), {
      target: { value: "draft text" },
    });
    expect(screen.queryByRole("button", { name: "Start a voice call" })).toBeNull();
    expect(screen.getByRole("button", { name: "Send ↑" })).toBeTruthy();
  });

  it("keeps voice reachable from the composer, not the title row", async () => {
    renderChat(null);
    // Voice moved out of the header, but it must stay reachable in an ACTIVE
    // conversation too, so it lives with the composer tools rather than in a
    // banner that only the empty state renders.
    await waitFor(() => {
      expect(document.querySelector(".composer-tools")).toBeTruthy();
    });
    expect(document.querySelector(".chat-header-actions .voice-call")).toBeNull();
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

  it("collapses the desktop rail from the header toggle", async () => {
    api.conversation.mockResolvedValue({ messages: [], active_run_id: null });
    renderChat("conversation-a");
    await screen.findByRole("heading", { level: 1, name: "Renewal outreach" });

    fireEvent.click(screen.getByRole("button", { name: "Hide the task panel" }));
    expect(document.querySelector(".chat-layout")?.getAttribute("data-rail-collapsed"))
      .toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "Show the task panel" }));
    expect(document.querySelector(".chat-layout")?.getAttribute("data-rail-collapsed"))
      .toBeNull();
  });

  it("counts subagents conversation-wide, including settled turns", async () => {
    api.conversation.mockResolvedValue({
      messages: [
        { id: "m1", role: "user", content: "Do the renewals" },
        {
          id: "m2", role: "assistant", content: "Done", events: [
            { type: "subagent", child_run_id: "r1", task: "Read health signals" },
            { type: "subagent", child_run_id: "r2", task: "Draft outreach" },
          ],
        },
      ],
      active_run_id: null,
    });
    renderChat("conversation-a");

    expect(await screen.findByText("2 subagents")).toBeTruthy();
  });

  it("replays a settled approval as a card that cannot be re-answered", async () => {
    api.conversation.mockResolvedValue({
      messages: [
        { id: "m1", role: "user", content: "Do the renewals" },
        {
          id: "m2", role: "assistant", content: "Stopped for approval", events: [
            {
              type: "hitl",
              hitl_request_id: "h1",
              kind: "approval",
              question: "Raise 3 tickets",
              options: [],
              verb: "ticket.create",
            },
          ],
        },
      ],
      active_run_id: null,
    });
    renderChat("conversation-a");

    expect(await screen.findByText("Raise 3 tickets")).toBeTruthy();
    // The request belongs to a dead turn: no approve/deny is offered.
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.getByText(/can no longer be answered here/)).toBeTruthy();
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
