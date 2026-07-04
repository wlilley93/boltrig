import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import * as apiClient from "@/api/client";
import type { ChatAttachment } from "@/api/types";
import { useChatStreamActions } from "@/panels/chat/useChatStreamActions";
import { normalizeEvents } from "@/panels/chatTurn";
import { clearApiMocks, mockApi } from "../../helpers";
import type { ChatPanelState } from "@/panels/chat/useChatState";
import type { ChatDerivedState } from "@/panels/chat/useChatDerived";
import type { RailState } from "@/panels/chat/types";

function makeMockState(overrides: Partial<ChatPanelState> = {}): ChatPanelState {
  const alive = { current: true };
  const abortRef = { current: null as AbortController | null };
  const turnTextRef = { current: "" };
  const turnCancelledRef = { current: false };
  const pendingConvId = { current: null as string | null };
  const suppressDictationRef = { current: false };
  const dictationBaseRef = { current: "" };
  const messagesRef = { current: null as HTMLElement | null };
  const pinnedRef = { current: false };
  const inputRef = { current: null as HTMLTextAreaElement | null };
  const fileInputRef = { current: null as HTMLInputElement | null };

  const railState: RailState = {
    mode: "list",
    items: [],
    nextOffset: null,
    loading: false,
    loadingMore: false,
    error: null,
    errorStatus: null,
  };

  const state = {
    alive,
    abortRef,
    turnTextRef,
    turnCancelledRef,
    pendingConvId,
    suppressDictationRef,
    dictationBaseRef,
    messagesRef,
    pinnedRef,
    inputRef,
    fileInputRef,
    input: "",
    attachments: [] as ChatAttachment[],
    activeId: null as string | null,
    streaming: false,
    readAloud: false,
    regenerating: null as string | null,
    liveEvents: [],
    messages: [],
    msgsLoading: false,
    msgsError: null,
    streamError: null,
    stopped: false,
    showJump: false,
    pendingUser: null as string | null,
    pendingAttachments: [] as ChatAttachment[],
    chatSearchTerm: "",
    showLive: false,
    dictation: {
      supported: false,
      listening: false,
      start: vi.fn(),
      stop: vi.fn(),
      error: null,
    },
    speech: {
      supported: true,
      speakingKey: null,
      speak: vi.fn(),
      cancel: vi.fn(),
    },
    rail: {
      state: railState,
      reload: vi.fn(),
      loadMore: vi.fn(),
    },
    setInput: vi.fn(),
    setStreamError: vi.fn(),
    setAttachError: vi.fn(),
    setStopped: vi.fn(),
    setPendingUser: vi.fn(),
    setPendingAttachments: vi.fn(),
    setAttachments: vi.fn(),
    setLiveEvents: vi.fn(),
    setStreaming: vi.fn(),
    setActiveId: vi.fn(),
    setMsgsError: vi.fn(),
    setRegenerating: vi.fn(),
    setShowJump: vi.fn(),
    ...overrides,
  } as unknown as ChatPanelState;

  return state;
}

function makeDerived(overrides: Partial<ChatDerivedState> = {}): ChatDerivedState {
  return {
    live: normalizeEvents([]),
    railItems: [],
    showLive: false,
    isEmpty: true,
    compactedCount: 0,
    displayedMessages: [],
    visibleMessages: [],
    firstVisibleIndex: 0,
    slashOpen: false,
    contextRemaining: 128,
    ...overrides,
  };
}

describe("useChatStreamActions", () => {
  afterEach(() => {
    clearApiMocks();
  });

  it("exposes the five stream actions", () => {
    const state = makeMockState();
    const derived = makeDerived();
    const loadConversation = vi.fn();
    const { result } = renderHook(() => useChatStreamActions(state, derived, loadConversation));
    expect(typeof result.current.send).toBe("function");
    expect(typeof result.current.reconnect).toBe("function");
    expect(typeof result.current.stopTurn).toBe("function");
    expect(typeof result.current.regenerate).toBe("function");
    expect(typeof result.current.watchAgain).toBe("function");
  });

  it("send starts a chat stream and finalizes the conversation", async () => {
    const streamChat = vi.spyOn(apiClient, "streamChat").mockResolvedValue(undefined);
    const loadConversation = vi.fn().mockResolvedValue(undefined);
    const state = makeMockState({
      input: "hello",
      activeId: "conv-1",
      attachments: [],
    });
    const derived = makeDerived();
    const { result } = renderHook(() => useChatStreamActions(state, derived, loadConversation));

    await act(async () => {
      await result.current.send();
    });

    expect(state.setInput).toHaveBeenCalledWith("");
    expect(state.setPendingUser).toHaveBeenCalledWith("hello");
    expect(state.setStreaming).toHaveBeenCalledWith(true);
    expect(streamChat).toHaveBeenCalledWith(
      { message: "hello", conversation_id: "conv-1" },
      expect.any(Function),
      expect.any(AbortSignal),
    );
    expect(loadConversation).toHaveBeenCalledWith("conv-1");
    expect(state.rail.reload).toHaveBeenCalled();
  });

  it("send does nothing when the composer is empty and streaming is false", async () => {
    const streamChat = vi.spyOn(apiClient, "streamChat").mockResolvedValue(undefined);
    const state = makeMockState({ input: "", attachments: [] });
    const { result } = renderHook(() => useChatStreamActions(state, makeDerived(), vi.fn()));
    await act(async () => {
      await result.current.send();
    });
    expect(streamChat).not.toHaveBeenCalled();
  });

  it("reconnect loads the active conversation and resets pending state", async () => {
    const loadConversation = vi.fn().mockResolvedValue(undefined);
    const state = makeMockState({ activeId: "conv-2" });
    const { result } = renderHook(() => useChatStreamActions(state, makeDerived(), loadConversation));

    await act(async () => {
      await result.current.reconnect();
    });

    expect(state.setStreamError).toHaveBeenCalledWith(null);
    expect(loadConversation).toHaveBeenCalledWith("conv-2");
    expect(state.rail.reload).toHaveBeenCalled();
    expect(state.setPendingUser).toHaveBeenCalledWith(null);
    expect(state.setPendingAttachments).toHaveBeenCalledWith([]);
    expect(state.setLiveEvents).toHaveBeenCalledWith([]);
    expect(state.setStopped).toHaveBeenCalledWith(false);
  });

  it("stopTurn aborts the stream when no run id is available", async () => {
    const abort = vi.fn();
    const controller = { signal: new AbortController().signal, abort } as unknown as AbortController;
    const state = makeMockState({ abortRef: { current: controller } });
    const derived = makeDerived();
    const { result } = renderHook(() => useChatStreamActions(state, derived, vi.fn()));

    await act(async () => {
      await result.current.stopTurn();
    });

    expect(state.turnCancelledRef.current).toBe(true);
    expect(state.speech.cancel).toHaveBeenCalled();
    expect(state.setStopped).toHaveBeenCalledWith(true);
    expect(abort).toHaveBeenCalled();
    expect(state.setStreaming).toHaveBeenCalledWith(false);
  });

  it("regenerate calls the regenerate endpoint and refreshes the conversation", async () => {
    mockApi({ regenerateMessage: { status: "ok" }, conversation: { messages: [] } });
    const loadConversation = vi.fn().mockResolvedValue(undefined);
    const state = makeMockState({ activeId: "conv-3" });
    const { result } = renderHook(() => useChatStreamActions(state, makeDerived(), loadConversation));

    await act(async () => {
      await result.current.regenerate("msg-1");
    });

    expect(state.setRegenerating).toHaveBeenCalledWith("msg-1");
    expect(state.setRegenerating).toHaveBeenLastCalledWith(null);
    expect(loadConversation).toHaveBeenCalledWith("conv-3");
    expect(state.rail.reload).toHaveBeenCalled();
  });

  it("watchAgain follows a live run when a run id is present", async () => {
    const streamRunEvents = vi.spyOn(apiClient, "streamRunEvents").mockResolvedValue(undefined);
    const loadConversation = vi.fn().mockResolvedValue(undefined);
    const live = normalizeEvents([
      { type: "message_start", run_id: "run-5", conversation_id: "conv-5" },
    ] as unknown[]);
    const state = makeMockState({ activeId: "conv-5" });
    const derived = makeDerived({ live });
    const { result } = renderHook(() => useChatStreamActions(state, derived, loadConversation));

    await act(async () => {
      await result.current.watchAgain();
    });

    expect(state.setStreaming).toHaveBeenCalledWith(true);
    expect(streamRunEvents).toHaveBeenCalledWith(
      "run-5",
      expect.any(Function),
      { signal: expect.any(AbortSignal), follow: true },
    );
    expect(loadConversation).toHaveBeenCalledWith("conv-5");
  });

  it("watchAgain falls back to reconnect when no run id is present", async () => {
    const loadConversation = vi.fn().mockResolvedValue(undefined);
    const state = makeMockState({ activeId: "conv-6" });
    const { result } = renderHook(() => useChatStreamActions(state, makeDerived(), loadConversation));

    await act(async () => {
      await result.current.watchAgain();
    });

    expect(state.setStreamError).toHaveBeenCalledWith(null);
    expect(loadConversation).toHaveBeenCalledWith("conv-6");
  });
});
