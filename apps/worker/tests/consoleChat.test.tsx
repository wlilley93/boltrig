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
// markup shape (.voice-idle > .primary-button) because the empty-draft
// primary starts the call through that button.
vi.mock("../src/components/VoiceCall", () => ({
  VoiceCall: ({ onCallActive }: { onCallActive?(active: boolean): void }) => (
    <div className="voice-idle">
      <button
        className="primary-button"
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
    expect(screen.getByRole("heading", { level: 1, name: "What needs doing?" }))
      .toBeTruthy();
    expect(document.querySelectorAll(".welcome .starter-card").length).toBe(4);
    expect(document.querySelectorAll(".welcome .starter-icon").length).toBe(4);
    await waitFor(() => {
      expect(document.querySelector(".welcome .familiar-stage")).toBeNull();
    });
    // The New state draws no header bar at all (so no familiar or settings
    // control can sit in one). Theme remains available from Settings.
    expect(document.querySelector(".chat-header")).toBeNull();
    expect(screen.queryByRole("button", { name: "Toggle theme" })).toBeNull();

    // At 30px the canonical ladder uses its glossy Stage, not the flat badge.
    // No chief genotype exists in this route's contract, so the renderer must
    // state that absence instead of borrowing a child identity.
    const voiceFamiliar = screen.getByRole("img", {
      name: "chief of staff Familiar · ready",
    });
    expect(voiceFamiliar.classList.contains("familiar-stage")).toBeTruthy();
    expect(voiceFamiliar.classList.contains("conversation")).toBeTruthy();
    expect(voiceFamiliar.getAttribute("data-genotype-source")).toBe("unbound");
    expect(voiceFamiliar.closest(".voice-intro")).toBeTruthy();
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

  it("keeps voice start in the round composer control", () => {
    renderChat(null);

    expect(screen.queryByText("Try boltrig Voice")).toBeNull();
    expect(screen.getByRole("button", { name: "Start a voice call" })).toBeTruthy();
    expect(screen.queryByText("Call options")).toBeNull();
  });

  it("turns the empty-draft primary into a voice call, and says so", async () => {
    renderChat(null);

    // Empty draft: the primary is the round voice control, with no explanatory footer.
    expect(screen.queryByText("Nothing typed, so the round button starts a voice call."))
      .toBeNull();
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
    api.conversation.mockResolvedValue({ messages: [], active_run_id: null });
    renderChat("conversation-a");
    // Voice moved out of the header, but it must stay reachable in an ACTIVE
    // conversation too, so it lives with the composer tools rather than in a
    // banner that only the empty state renders.
    await waitFor(() => {
      expect(document.querySelector(".composer-tools")).toBeTruthy();
    });
    expect(document.querySelector(".composer.conversation-context:not(.closed)"))
      .toBeTruthy();
    expect(screen.getByRole("button", { name: "Policy" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Attach files" }).querySelector("svg"))
      .toBeTruthy();
    expect(document.querySelector(".chat-header-actions .voice-call")).toBeNull();
  });

  it("does not attribute a main response to its first child subagent", async () => {
    api.conversation.mockResolvedValue({
      messages: [
        { id: "m1", role: "user", content: "First ask" },
        { id: "m2", role: "assistant", content: "Older answer" },
        { id: "m3", role: "user", content: "Second ask" },
        {
          id: "m4",
          role: "assistant",
          content: "Newest answer",
          events: [{
            type: "subagent",
            child_run_id: "child-lyell",
            task: "Read account health",
            name: "Lyell",
          }],
        },
      ],
      active_run_id: null,
    });
    renderChat("conversation-a");

    const answer = await screen.findByText("Newest answer");
    const article = answer.closest("article.message.assistant");
    expect(article?.querySelector(".message-author")).toBeNull();
    expect(article?.querySelector(".subagent-chip")?.textContent).toContain("Lyell");
    expect(article?.querySelector(".subagent-fanout")).toBeNull();
    expect(article?.querySelectorAll(".transcript-subagent-chip")).toHaveLength(1);
    expect(article?.querySelector(".familiar-stage")).toBeNull();
    expect(document.querySelectorAll("article.message.assistant .message-author").length)
      .toBe(0);
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

    // The call owns the one centred Stage. The main response stays unlabelled:
    // no child identity is borrowed merely because a call is active.
    await waitFor(() => {
      const stages = document.querySelectorAll(".familiar-stage");
      expect(stages.length).toBe(1);
      expect(stages[0]!.closest(".voice-stage")).toBeTruthy();
      expect(stages[0]!.classList.contains("voice")).toBeTruthy();
    });
    const newest = [...document.querySelectorAll("article.message.assistant")]
      .find((article) => article.textContent?.includes("Newest answer"));
    expect(newest?.querySelector(".message-author")).toBeNull();
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

  it("keeps real conversation mutations behind a phone-only Task actions disclosure", async () => {
    vi.stubGlobal("matchMedia", vi.fn().mockImplementation((query: string) => ({
      matches: query === "(max-width: 1020px)" || query === "(max-width: 640px)",
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));
    api.conversation.mockResolvedValue({
      messages: [{
        id: "assistant-a",
        role: "assistant",
        content: "Current answer",
        created_at: "2026-01-01T00:00:00Z",
      }],
      active_run_id: null,
    });
    try {
      renderChat("conversation-a");
      fireEvent.click(await screen.findByRole("button", { name: "Task details" }));
      const summary = screen.getByText("Task actions");
      const disclosure = summary.closest("details") as HTMLDetailsElement;
      expect(disclosure.open).toBe(false);
      fireEvent.click(summary);
      expect(disclosure.open).toBe(true);
      expect(screen.getByLabelText("Conversation title")).toBeTruthy();
      expect(screen.getByRole("button", { name: "Close conversation" })).toBeTruthy();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("titles the header with the real conversation, not a slogan", async () => {
    api.conversation.mockResolvedValue({ messages: [], active_run_id: null });
    renderChat("conversation-a");

    expect(await screen.findByRole("heading", { level: 1, name: "Renewal outreach" }))
      .toBeTruthy();
    expect(screen.getByRole("region", { name: "Conversation transcript" }).hasAttribute("aria-live"))
      .toBe(false);
  });

  it("summarises tool use naturally and retains the exact expandable detail", async () => {
    api.conversation.mockResolvedValue({
      messages: [{
        id: "assistant-a",
        role: "assistant",
        content: "I found the file.",
        events: [
          { type: "message_start", run_id: "run-a", conversation_id: "conversation-a" },
          { type: "tool_call", call_id: "call-a", tool: "file.read", args_summary: { keys: ["path"] } },
          { type: "tool_result", call_id: "call-a", verb: "file.read", status: "ok" },
          { type: "message_end", run_id: "run-a" },
        ],
      }],
      active_run_id: null,
    });
    renderChat("conversation-a");

    const summaryText = await screen.findByText("Read files");
    const summary = summaryText.closest("summary");
    expect(summary?.getAttribute("aria-label")).toBe("Read files. 1 tool detail");
    expect(summary?.querySelector(".transcript-tool-glyph")?.getAttribute("data-kind"))
      .toBe("read");
    expect(document.querySelector(".work-rule")).toBeNull();
    expect(document.querySelector(".activity-row")).toBeNull();

    fireEvent.click(summary!);
    const detail = document.querySelector(".transcript-tool-detail");
    expect(detail?.querySelector("code")?.textContent).toBe("file.read");
    expect(detail?.querySelector("[data-status]")?.textContent).toBe("ok");
    expect(document.querySelector(".tool-icon-read")).toBeTruthy();
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

  it("flips the theme from an active conversation header and persists the choice", async () => {
    api.conversation.mockResolvedValue({ messages: [], active_run_id: null });
    renderChat("conversation-a");

    await screen.findByRole("heading", { level: 1, name: "Renewal outreach" });

    fireEvent.click(screen.getByRole("button", { name: "Toggle theme" }));
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem("boltrig-worker-theme")).toBe("light");

    fireEvent.click(screen.getByRole("button", { name: "Toggle theme" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});
