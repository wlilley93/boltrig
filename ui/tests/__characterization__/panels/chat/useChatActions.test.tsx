import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";

import { api } from "@/api/client";
import type { ChatMessage, ConversationResponse } from "@/api/types";
import { useChatPanel } from "@/panels/chat/useChatPanel";
import { clearApiMocks, mockApi } from "../../helpers";

function transcript(id: string): ChatMessage[] {
  return [
    {
      id,
      role: "assistant",
      content: `body of ${id}`,
      created_at: "2026-01-01T00:00:00Z",
    },
  ];
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

function mockRail(): void {
  mockApi({
    listConversations: { conversations: [], next_offset: null },
    searchConversations: { results: [], next_offset: null },
    conversation: { messages: [] },
  });
}

describe("useChatActions conversation loading", () => {
  afterEach(() => {
    cleanup();
    clearApiMocks();
  });

  it("clears the previous transcript when a newly selected conversation fails to load", async () => {
    mockRail();
    vi.spyOn(api, "conversation").mockResolvedValue({ messages: transcript("msg-a") });

    const { result } = renderHook(() => useChatPanel());
    await act(async () => {
      result.current.selectConversation("conv-a");
    });
    expect(result.current.messages.map((m) => m.id)).toEqual(["msg-a"]);

    vi.spyOn(api, "conversation").mockRejectedValue(new Error("forbidden"));
    await act(async () => {
      result.current.selectConversation("conv-b");
    });

    expect(result.current.activeId).toBe("conv-b");
    expect(result.current.msgsError).not.toBeNull();
    expect(
      result.current.messages.map((m) => m.id),
      "conversation A's transcript is still rendered while activeId is conversation B, whose load failed",
    ).toEqual([]);
  });

  it("drops a superseded transcript response so the newest selection wins", async () => {
    mockRail();
    const first = deferred<ConversationResponse>();
    const second = deferred<ConversationResponse>();
    vi.spyOn(api, "conversation").mockImplementation((id: string) =>
      id === "conv-a" ? first.promise : second.promise,
    );

    const { result } = renderHook(() => useChatPanel());
    act(() => {
      result.current.selectConversation("conv-a");
    });
    act(() => {
      result.current.selectConversation("conv-b");
    });

    // The newest load lands first, then the superseded one resolves late.
    await act(async () => {
      second.resolve({ messages: transcript("msg-b") });
      await second.promise;
    });
    await act(async () => {
      first.resolve({ messages: transcript("msg-a") });
      await first.promise;
    });

    expect(result.current.activeId).toBe("conv-b");
    expect(
      result.current.messages.map((m) => m.id),
      "a superseded transcript fetch overwrote the active conversation's messages",
    ).toEqual(["msg-b"]);
    expect(
      result.current.msgsLoading,
      "a superseded transcript fetch cleared the loading flag of the newer load",
    ).toBe(false);
  });

  // The recency guard alone does NOT cover this, which is why the id guard
  // exists. Regenerate awaits a real model turn and only then reloads, using the
  // conversation id its closure captured; nothing disables the rail meanwhile. So
  // the stale reload is issued LAST and a monotonic guard would sanction it.
  it("does not repaint the conversation a regenerate started in after the pane has moved on", async () => {
    mockRail();
    vi.spyOn(api, "conversation").mockImplementation(async (id: string) => ({
      messages: transcript(id === "conv-a" ? "msg-a" : "msg-b"),
    }));
    const regen = deferred<{ status: string }>();
    vi.spyOn(api, "regenerateMessage").mockImplementation(() => regen.promise as never);

    const { result } = renderHook(() => useChatPanel());
    await act(async () => {
      result.current.selectConversation("conv-a");
    });
    expect(result.current.messages.map((m) => m.id)).toEqual(["msg-a"]);

    act(() => {
      result.current.regenerate("msg-a");
    });
    await act(async () => {
      result.current.selectConversation("conv-b");
    });
    expect(result.current.messages.map((m) => m.id)).toEqual(["msg-b"]);

    // The regenerate finishes now, and its reload is the newest request.
    await act(async () => {
      regen.resolve({ status: "ok" });
      await regen.promise;
    });

    expect(result.current.activeId).toBe("conv-b");
    expect(
      result.current.messages.map((m) => m.id),
      "conversation A repainted under conversation B's id: the regenerate's reload was newest, so recency alone sanctioned it",
    ).toEqual(["msg-b"]);
    expect(
      result.current.msgsLoading,
      "the disowned reload left the spinner on with nothing coming to clear it",
    ).toBe(false);
  });
});
