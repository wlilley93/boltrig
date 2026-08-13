// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  normalizeEvents,
  type ChatEvent,
} from "@wlilley93/boltrig-web-sdk";

import { OrderedWorkTranscript } from "../src/components/chat/OrderedWorkTranscript";
import { ChatView } from "../src/components/ChatView";

const api = vi.hoisted(() => ({
  chatModelChoices: vi.fn(),
  artifacts: vi.fn(),
  chatConfig: vi.fn(),
  conversation: vi.fn(),
  conversations: vi.fn(),
  followConversation: vi.fn(),
  modelProfiles: vi.fn(),
  streamChat: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));
vi.mock("../src/components/VoiceCall", () => ({ VoiceCall: () => null }));

beforeEach(() => {
  api.chatModelChoices.mockResolvedValue({
    status: "ok",
    reason: null,
    choices: [],
    default_choice_id: "opaque-default-route",
    default_model_name: "openai/gpt-5.4",
    default_available: true,
  });
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
});

function directOrder(container: HTMLElement): string[] {
  return [...container.children].map((node) => (
    node.classList.contains("work-disclosure") ? "work" : node.textContent ?? ""
  ));
}

describe("ordered transcript work receipts", () => {
  it("interleaves exact tool receipts between the prose deltas that surround them", () => {
    const events: ChatEvent[] = [
      { type: "message_start", run_id: "run-a", conversation_id: "conversation-a" },
      { type: "text_delta", delta: "First." },
      { type: "tool_call", call_id: "call-figma", tool: "figma.get_design_context" },
      { type: "tool_result", call_id: "call-figma", status: "ok" },
      { type: "tool_call", call_id: "call-read", tool: "file.read" },
      { type: "tool_result", call_id: "call-read", status: "ok" },
      { type: "text_delta", delta: "Second." },
      { type: "tool_call", call_id: "call-edit", tool: "apply_patch" },
      { type: "tool_result", call_id: "call-edit", status: "ok" },
      { type: "tool_call", call_id: "call-command", tool: "exec_command" },
      { type: "tool_result", call_id: "call-command", status: "ok" },
      { type: "text_delta", delta: "Done." },
      { type: "message_end", run_id: "run-a" },
    ];
    const { container } = render(
      <main>
        <OrderedWorkTranscript
          content="First.Second.Done."
          events={events}
          turn={normalizeEvents(events)}
        />
      </main>,
    );

    expect(directOrder(container.querySelector("main")!)).toEqual([
      "First.",
      "work",
      "Second.",
      "work",
      "Done.",
    ]);
    const summaries = [
      screen.getByText("Used Figma integration, read files").closest("summary")!,
      screen.getByText("Edited files, ran commands").closest("summary")!,
    ];
    summaries.forEach((summary) => fireEvent.click(summary));
    const details = screen.getAllByRole("list", { name: "Exact tool details" });
    expect(details).toHaveLength(2);
    expect(details[0]!.textContent).toContain("figma.get_design_contextok");
    expect(details[0]!.textContent).toContain("file.readok");
    expect(details[0]!.textContent).not.toContain("apply_patch");
    expect(details[1]!.textContent).toContain("apply_patchok");
    expect(details[1]!.textContent).toContain("exec_commandok");
    expect(details[1]!.textContent).not.toContain("file.read");
  });

  it("falls back to canonical prose followed by one aggregate when deltas do not match", () => {
    const events: ChatEvent[] = [
      { type: "text_delta", delta: "Stale relay copy." },
      { type: "tool_call", call_id: "call-a", tool: "file.read" },
      { type: "tool_result", call_id: "call-a", status: "ok" },
      { type: "tool_call", call_id: "call-b", tool: "exec_command" },
      { type: "tool_result", call_id: "call-b", status: "ok" },
    ];
    const { container } = render(
      <main>
        <OrderedWorkTranscript
          content="Canonical stored answer."
          events={events}
          settled
          turn={normalizeEvents(events)}
        />
      </main>,
    );

    expect(directOrder(container.querySelector("main")!)).toEqual([
      "Canonical stored answer.",
      "work",
    ]);
    expect(document.body.textContent).not.toContain("Stale relay copy.");
    expect(screen.getByText("Read files, ran commands")).toBeTruthy();
    expect(screen.getByRole("list", { name: "Exact tool details" }).children)
      .toHaveLength(2);
  });

  it("uses ordered raw events for a production-shaped persisted assistant message", async () => {
    api.conversation.mockResolvedValue({
      messages: [{
        id: "assistant-a",
        role: "assistant",
        run_id: "run-a",
        content: "Before.After.",
        events: [
          { type: "text_delta", delta: "Before." },
          { type: "tool_call", call_id: "call-a", tool: "file.read" },
          { type: "tool_result", call_id: "call-a", status: "ok" },
          { type: "text_delta", delta: "After." },
        ],
      }],
      active_run_id: null,
    });
    render(
      <ChatView conversationId="conversation-a" onConversation={vi.fn()} onChanged={vi.fn()} />,
    );

    const content = await waitFor(() => {
      const node = screen.getByText("Before.").closest<HTMLElement>(".message-content");
      expect(node).toBeTruthy();
      return node!;
    });
    expect(directOrder(content)).toEqual(["Before.", "work", "After."]);
  });

  it("passes live raw relay events through the same ordered presentation", async () => {
    api.conversation.mockResolvedValue({ messages: [], active_run_id: "run-live" });
    api.followConversation.mockImplementation(async (_id, onFrame) => {
      onFrame({
        cursor: 0,
        event: {
          type: "message_start",
          run_id: "run-live",
          conversation_id: "conversation-a",
        },
      });
      onFrame({ cursor: 1, event: { type: "text_delta", delta: "Live before." } });
      onFrame({
        cursor: 2,
        event: { type: "tool_call", call_id: "call-live", tool: "exec_command" },
      });
      onFrame({
        cursor: 3,
        event: { type: "tool_result", call_id: "call-live", status: "ok" },
      });
      onFrame({ cursor: 4, event: { type: "text_delta", delta: "Live after." } });
      return await new Promise(() => {});
    });
    render(
      <ChatView conversationId="conversation-a" onConversation={vi.fn()} onChanged={vi.fn()} />,
    );

    const content = await waitFor(() => {
      const node = screen.getByText("Live before.").closest<HTMLElement>(".message-content");
      expect(node).toBeTruthy();
      return node!;
    });
    expect(directOrder(content)).toEqual([
      "Response in progress.",
      "Live before.",
      "work",
      "Live after.",
    ]);
  });
});
