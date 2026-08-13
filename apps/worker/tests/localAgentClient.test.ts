// @vitest-environment happy-dom

import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({
  Channel: class MockChannel<T> { onmessage?: (message: T) => void },
  invoke: vi.fn(),
}));

import {
  archiveLocalConversation,
  listLocalConversations,
  loadLocalConversation,
  localConversationId,
  localEventToChatEvent,
  localThreadId,
  restoreLocalConversation,
  saveLocalConversation,
  type LocalConversation,
} from "../src/localAgentClient";

beforeEach(() => {
  localStorage.clear();
});

describe("desktop local-agent projection", () => {
  it("keeps opaque local thread ids distinct from cloud conversations", () => {
    expect(localConversationId("thread-1")).toBe("local:thread-1");
    expect(localThreadId("local:thread-1")).toBe("thread-1");
    expect(localThreadId("cloud-thread-1")).toBeNull();
    expect(localThreadId("local:thread id")).toBeNull();
  });

  it("stores and archives the local projection without claiming to delete the Codex thread", () => {
    const conversation = sampleConversation();
    saveLocalConversation(conversation);

    expect(listLocalConversations()).toEqual([{
      id: conversation.id,
      title: conversation.title,
      status: "active",
      updated_at: conversation.updated_at,
    }]);
    expect(archiveLocalConversation(conversation.id)).toBe(true);
    expect(loadLocalConversation(conversation.id)?.status).toBe("closed");
    expect(archiveLocalConversation(conversation.id)).toBe(false);
    expect(restoreLocalConversation(conversation.id)).toBe(true);
    expect(loadLocalConversation(conversation.id)?.status).toBe("active");
    expect(restoreLocalConversation(conversation.id)).toBe(false);
  });

  it("projects only bounded transcript semantics from native events", () => {
    expect(localEventToChatEvent({
      type: "message_start",
      thread_id: "thread-1",
      turn_id: "turn-1",
      model: "gpt-5.4",
    })).toEqual({
      type: "message_start",
      conversation_id: "local:thread-1",
      run_id: "turn-1",
    });
    expect(localEventToChatEvent({
      type: "tool_started",
      item_id: "item-1",
      tool: "Local shell",
    })).toEqual({
      type: "tool_call",
      call_id: "item-1",
      tool: "Local shell",
      args_summary: { keys: [], count: 0 },
    });
    expect(localEventToChatEvent({
      type: "approval_resolved",
      item_id: "item-1",
      decision: "accepted",
    })).toBeNull();
  });

  it("rejects malformed persisted transcript events instead of replaying them", () => {
    const conversation = sampleConversation();
    conversation.messages = [{
      id: "message-2",
      role: "assistant",
      content: "unsafe projection",
      created_at: conversation.updated_at,
      events: [{ type: "invented_native_event", secret: "must not replay" }] as never,
    }];
    localStorage.setItem(
      "boltrig.local-conversations.v1",
      JSON.stringify([conversation]),
    );

    expect(listLocalConversations()).toEqual([]);
  });
});

function sampleConversation(): LocalConversation {
  return {
    id: "local:thread-1",
    thread_id: "thread-1",
    root_id: "root-1",
    title: "Inspect the workspace",
    status: "active",
    model: "gpt-5.4",
    messages: [{
      id: "message-1",
      role: "user",
      content: "Inspect the workspace",
      created_at: "2026-08-13T10:00:00.000Z",
    }],
    created_at: "2026-08-13T10:00:00.000Z",
    updated_at: "2026-08-13T10:00:00.000Z",
  };
}
