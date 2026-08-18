// @vitest-environment happy-dom

import { useLayoutEffect, useRef, useState } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  capabilities: vi.fn(),
  callEvents: vi.fn(),
  callUsage: vi.fn(),
  calls: vi.fn(),
  createCall: vi.fn(),
  currentCall: vi.fn(),
  endCall: vi.fn(),
  reopenCall: vi.fn(),
  refreshCallMedia: vi.fn(),
}));

const native = vi.hoisted(() => ({ isDesktop: false }));

vi.mock("../src/client", () => ({ client: api }));
vi.mock("../src/desktop", () => native);

import { VoiceCall } from "../src/components/VoiceCall";
import { saveCharacterLocal } from "../src/character";

const call = {
  id: "call-a",
  conversation_id: "conversation-a",
  status: "creating" as const,
  provider_class: "realtime_voice" as const,
  participants: [
    { id: "alice", label: "You", kind: "user" as const },
    { id: "agent", label: "Boltrig", kind: "agent" as const },
  ],
};

const mediaResult = {
  call,
  media_token: "one-time-media-token",
  websocket_url: "/voice/v1/calls/call-a/media",
};

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

function VoiceCallWithPersistentOpener({ onError = vi.fn() }: { onError?: (message: string) => void }) {
  const openerRef = useRef<HTMLButtonElement>(null);
  return (
    <>
      <button
        onClick={() => document.querySelector<HTMLButtonElement>(
          ".voice-idle > button.primary-button",
        )?.click()}
        ref={openerRef}
        type="button"
      >
        Open voice call
      </button>
      <VoiceCall
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onError={onError}
      />
    </>
  );
}

function RealtimeUnavailableHarness() {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [error, setError] = useState("");
  // Mirrors ChatView's hard route-boundary reset.
  useLayoutEffect(() => setError(""), [conversationId]);
  return (
    <>
      <VoiceCall
        conversationId={conversationId}
        embedded
        onConversation={setConversationId}
        onError={setError}
      />
      <span data-testid="voice-conversation">{conversationId ?? "new"}</span>
      {error && <p role="alert">{error}</p>}
    </>
  );
}

class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static instances: FakeWebSocket[] = [];

  readyState = FakeWebSocket.CONNECTING;
  binaryType = "";
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  send = vi.fn();
  close = vi.fn(() => {
    this.readyState = 3;
  });

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }
}

class FakeAudioNode {
  connect = vi.fn();
  disconnect = vi.fn();
}

class FakeAudioContext {
  static instances: FakeAudioContext[] = [];
  static nextCurrentTimes: number[] = [];

  sampleRate = 48_000;
  currentTime: number;
  destination = new FakeAudioNode();
  resume = vi.fn().mockResolvedValue(undefined);
  close = vi.fn().mockResolvedValue(undefined);
  playbackSources: Array<FakeAudioNode & {
    buffer: unknown;
    onended: (() => void) | null;
    start: ReturnType<typeof vi.fn>;
    stop: ReturnType<typeof vi.fn>;
  }> = [];
  gains: Array<FakeAudioNode & { gain: { value: number } }> = [];
  createMediaStreamSource = vi.fn(() => new FakeAudioNode());
  createScriptProcessor = vi.fn(() => Object.assign(new FakeAudioNode(), {
    onaudioprocess: null,
  }));
  createGain = vi.fn(() => {
    const gain = Object.assign(new FakeAudioNode(), { gain: { value: 1 } });
    this.gains.push(gain);
    return gain;
  });
  analysers: Array<FakeAudioNode & {
    fftSize: number;
    micLevel: number;
    getFloatTimeDomainData: (frame: Float32Array) => void;
  }> = [];
  createAnalyser = vi.fn(() => {
    const analyser = Object.assign(new FakeAudioNode(), {
      fftSize: 0,
      smoothingTimeConstant: 0,
      frequencyBinCount: 512,
      getByteFrequencyData: vi.fn(),
      // Capture-side barge-in reads the time domain. `micLevel` is the constant
      // amplitude a test wants the microphone to be carrying.
      micLevel: 0,
      getFloatTimeDomainData(frame: Float32Array) {
        frame.fill(analyser.micLevel);
      },
    });
    this.analysers.push(analyser);
    return analyser;
  });
  createBuffer = vi.fn(() => ({
    duration: 1,
    getChannelData: () => new Float32Array(),
  }));
  createBufferSource = vi.fn(() => {
    const source = Object.assign(new FakeAudioNode(), {
      buffer: null as unknown,
      onended: null as (() => void) | null,
      start: vi.fn(),
      stop: vi.fn(),
    });
    this.playbackSources.push(source);
    return source;
  });

  constructor() {
    this.currentTime = FakeAudioContext.nextCurrentTimes.shift() ?? 0;
    FakeAudioContext.instances.push(this);
  }
}

const transcript = {
  id: "event-transcript-input",
  call_id: call.id,
  type: "transcript" as const,
  participant_id: "alice",
  payload: { text: "Earlier question", final: true, kind: "input" },
  created_at: "2026-07-29T10:00:00Z",
};
const pending = {
  id: "event-hitl-pending",
  call_id: call.id,
  type: "hitl" as const,
  participant_id: "agent",
  payload: {
    request_id: "approval-a",
    status: "pending",
    verb: "ticket.create",
  },
  created_at: "2026-07-29T10:00:01Z",
};
const output = {
  id: "event-transcript-output",
  call_id: call.id,
  type: "transcript" as const,
  participant_id: "agent",
  payload: { text: "Continuing now", final: true, kind: "output" },
  created_at: "2026-07-29T10:00:02Z",
};
const approved = {
  id: "event-hitl-approved",
  call_id: call.id,
  type: "hitl" as const,
  participant_id: "agent",
  payload: {
    request_id: "approval-a",
    status: "ok",
    verb: "ticket.create",
  },
  created_at: "2026-07-29T10:00:03Z",
};

beforeEach(() => {
  localStorage.removeItem("boltrig.character");
  delete document.documentElement.dataset.character;
  delete document.documentElement.dataset.visualPinRecoveredCallNotice;
  native.isDesktop = false;
  FakeWebSocket.instances = [];
  FakeAudioContext.instances = [];
  FakeAudioContext.nextCurrentTimes = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  vi.stubGlobal("AudioContext", FakeAudioContext);
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia: vi.fn().mockResolvedValue({
        getTracks: () => [{ stop: vi.fn() }],
      }),
    },
  });

  api.createCall.mockResolvedValue(mediaResult);
  api.calls.mockResolvedValue({ calls: [] });
  api.capabilities.mockResolvedValue({ agent_capabilities: [] });
  api.currentCall.mockResolvedValue({ call: null });
  api.reopenCall.mockResolvedValue({
    ...mediaResult,
    call: { ...call, status: "reconnecting" },
    media_token: "refreshed-media-token",
  });
  api.refreshCallMedia.mockResolvedValue({
    ...mediaResult,
    call: { ...call, status: "reconnecting" },
    media_token: "refreshed-media-token",
  });
  api.endCall.mockResolvedValue({
    ...call,
    status: "ended",
    ended_at: "2026-07-29T10:05:00Z",
  });
  api.callUsage.mockResolvedValue({
    call_id: call.id,
    usage: {
      input_audio_bytes: 48_000,
      output_audio_bytes: 48_000,
      tool_calls: 1,
      provider_input_tokens: 10,
      provider_output_tokens: 20,
      estimated_cost_micros: 1_000,
      pricing_revision: "test",
      cost_status: "estimated",
    },
  });
  api.callEvents
    .mockResolvedValueOnce({ events: [transcript, pending] })
    .mockResolvedValueOnce({ events: [transcript, pending, output, approved] })
    .mockResolvedValue({ events: [transcript, pending, output, approved] });
});

afterEach(() => {
  cleanup();
  document.querySelectorAll("[data-voice-modal-test-sibling]").forEach((element) => element.remove());
  delete document.documentElement.dataset.visualPinRecoveredCallNotice;
  localStorage.removeItem("boltrig.character");
  delete document.documentElement.dataset.character;
  vi.useRealTimers();
  vi.clearAllMocks();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("Worker realtime voice continuity", () => {
  it("keeps the typed unavailable notice after adopting its text conversation", async () => {
    api.createCall.mockResolvedValue({
      call: {
        ...call,
        conversation_id: "conversation-text-fallback",
        status: "realtime_unavailable",
      },
      media_token: null,
      text_continuation_conversation_id: "conversation-text-fallback",
      websocket_url: null,
    });

    render(<RealtimeUnavailableHarness />);
    fireEvent.click(screen.getByRole("button", { name: "Talk to the chief of staff" }));

    expect(await screen.findByText("conversation-text-fallback")).toBeTruthy();
    expect((await screen.findByRole("alert")).textContent).toBe(
      "Live voice is unavailable. You can continue here in text.",
    );
  });

  it("keeps conversation context accessible without painting call metadata", async () => {
    api.currentCall.mockResolvedValue({
      call: {
        ...call,
        status: "active",
        participants: [
          call.participants[0]!,
          { id: "chief", label: "chief of staff", kind: "agent" as const },
        ],
      },
    });
    api.callEvents.mockReset().mockResolvedValue({ events: [] });

    render(
      <VoiceCall
        conversationId="conversation-a"
        conversationTitle="Renewal outreach"
        onConversation={vi.fn()}
        onError={vi.fn()}
      />,
    );

    expect(await screen.findByText("Voice call for Renewal outreach")).toBeTruthy();
    expect(document.querySelector(".voice-call-title")).toBeNull();
    expect(document.querySelector(".voice-call-elapsed")).toBeNull();
  });

  it("keeps recovered connection copy out of the visual call chrome", async () => {
    api.currentCall.mockResolvedValue({ call: { ...call, status: "active" } });
    api.callEvents.mockReset().mockResolvedValue({ events: [] });

    render(
      <VoiceCall
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onError={vi.fn()}
      />,
    );
    const recoveryCopy = "A voice call from this conversation can be resumed.";
    expect(await screen.findByText(recoveryCopy)).toBeTruthy();
    expect(document.querySelector(".voice-call-notice")).toBeNull();
    expect(screen.queryByRole("button", { name: "Dismiss call notice" })).toBeNull();
  });

  it("shows an urgent approval exception until it is explicitly dismissed", async () => {
    api.currentCall.mockResolvedValue({ call: { ...call, status: "active" } });
    api.callEvents.mockReset().mockResolvedValue({ events: [pending] });

    render(
      <VoiceCall
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onError={vi.fn()}
      />,
    );
    const approvalCopy = "Approval needed for ticket.create. Review it in the originating chat to continue.";
    expect((await screen.findByText(approvalCopy)).closest("article")?.getAttribute(
      "data-urgent",
    )).toBe("true");
    // AWAITED. findByText above resolves when the approval copy appears, which is
    // not necessarily the render that also produced this button -- a synchronous
    // getByRole here races one commit, and that is how this test failed once under
    // full-suite parallelism and then passed twice on its own. findBy resolves
    // immediately when the element is already there, so it costs nothing.
    //
    // Note for anyone tempted to apply this to the whole file: three tests here run
    // under vi.useFakeTimers(), and findBy polls on REAL timers, so it can never
    // resolve inside them. Their synchronous getBy calls are load-bearing.
    fireEvent.click(await screen.findByRole("button", { name: "Dismiss call notice" }));
    await waitFor(() =>
      expect(screen.queryByText(approvalCopy)?.closest("article")).toBeNull());
  });

  it("does not reopen a stale recovered call after navigating from conversation A to B", async () => {
    const historyA = deferred<{ events: Array<typeof transcript | typeof pending> }>();
    api.currentCall.mockImplementation((requestedConversationId: string) => Promise.resolve({
      call: requestedConversationId === "conversation-a"
        ? { ...call, status: "active" as const }
        : null,
    }));
    api.callEvents.mockReset().mockReturnValue(historyA.promise);
    const onConversation = vi.fn();
    const onError = vi.fn();
    const view = render(
      <VoiceCall
        conversationId="conversation-a"
        onConversation={onConversation}
        onError={onError}
      />,
    );

    await waitFor(() => expect(api.callEvents).toHaveBeenCalledWith(call.id));
    expect(screen.getByRole("dialog", { name: "Voice call" })).toBeTruthy();

    view.rerender(
      <VoiceCall
        conversationId="conversation-b"
        onConversation={onConversation}
        onError={onError}
      />,
    );
    await waitFor(() => expect(api.currentCall).toHaveBeenCalledWith("conversation-b"));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Voice call" })).toBeNull());

    await act(async () => {
      historyA.resolve({ events: [transcript, pending] });
      await historyA.promise;
      await Promise.resolve();
    });

    expect(screen.queryByText("Earlier question")).toBeNull();
    expect(screen.queryByText("Waiting for approval")).toBeNull();
    expect(screen.queryByRole("dialog", { name: "Voice call" })).toBeNull();
    expect(screen.getByRole("button", { name: "◉ Start call" })).toBeTruthy();
  });

  it("does not attach deferred recovered-call usage to conversation B", async () => {
    const usageA = deferred<{
      call_id: string;
      usage: {
        input_audio_bytes: number;
        output_audio_bytes: number;
        tool_calls: number;
        provider_input_tokens: number;
        provider_output_tokens: number;
        estimated_cost_micros: number;
        pricing_revision: string;
        cost_status: "estimated";
      };
    }>();
    const callB = {
      ...call,
      id: "call-b",
      conversation_id: "conversation-b",
      status: "active" as const,
    };
    const usageEvent = {
      id: "event-usage-a",
      call_id: call.id,
      type: "usage" as const,
      participant_id: "agent",
      payload: {},
      created_at: "2026-07-29T10:00:04Z",
    };
    const endedB = {
      id: "event-ended-b",
      call_id: callB.id,
      type: "ended" as const,
      participant_id: "agent",
      payload: {},
      created_at: "2026-07-29T10:00:05Z",
    };
    api.currentCall.mockImplementation((requestedConversationId: string) => Promise.resolve({
      call: requestedConversationId === "conversation-a"
        ? { ...call, status: "active" as const }
        : callB,
    }));
    api.callEvents.mockReset().mockImplementation((callId: string) => Promise.resolve({
      events: callId === call.id ? [usageEvent] : [endedB],
    }));
    api.callUsage.mockReset().mockReturnValue(usageA.promise);
    const onConversation = vi.fn();
    const onError = vi.fn();
    const view = render(
      <VoiceCall
        conversationId="conversation-a"
        onConversation={onConversation}
        onError={onError}
      />,
    );

    await waitFor(() => expect(api.callUsage).toHaveBeenCalledWith(call.id));
    view.rerender(
      <VoiceCall
        conversationId="conversation-b"
        onConversation={onConversation}
        onError={onError}
      />,
    );
    expect(await screen.findByText("Call ended")).toBeTruthy();

    await act(async () => {
      usageA.resolve({
        call_id: call.id,
        usage: {
          input_audio_bytes: 48_000,
          output_audio_bytes: 48_000,
          tool_calls: 9,
          provider_input_tokens: 100,
          provider_output_tokens: 200,
          estimated_cost_micros: 9_000,
          pricing_revision: "stale-a",
          cost_status: "estimated",
        },
      });
      await usageA.promise;
      await Promise.resolve();
    });

    expect(screen.queryByText("Provider tokens")).toBeNull();
    expect(screen.queryByText("stale-a")).toBeNull();
  });

  it("keeps conversation B's notice when recovered history for A fails late", async () => {
    const historyA = deferred<{ events: [] }>();
    const callB = {
      ...call,
      id: "call-b",
      conversation_id: "conversation-b",
      status: "active" as const,
    };
    api.currentCall.mockImplementation((requestedConversationId: string) => Promise.resolve({
      call: requestedConversationId === "conversation-a"
        ? { ...call, status: "active" as const }
        : callB,
    }));
    api.callEvents.mockReset().mockImplementation((callId: string) => (
      callId === call.id ? historyA.promise : Promise.resolve({ events: [] })
    ));
    const onConversation = vi.fn();
    const onError = vi.fn();
    const view = render(
      <VoiceCall
        conversationId="conversation-a"
        onConversation={onConversation}
        onError={onError}
      />,
    );

    await waitFor(() => expect(api.callEvents).toHaveBeenCalledWith(call.id));
    view.rerender(
      <VoiceCall
        conversationId="conversation-b"
        onConversation={onConversation}
        onError={onError}
      />,
    );
    await waitFor(() => expect(api.callEvents).toHaveBeenCalledWith(callB.id));

    await act(async () => {
      historyA.reject(new Error("late history failure"));
      try {
        await historyA.promise;
      } catch {
        // The component owns this rejection; act waits for its guarded catch.
      }
      await Promise.resolve();
    });

    expect(screen.getByText("A voice call from this conversation can be resumed.")).toBeTruthy();
    expect(screen.queryByText(
      "Call history could not be restored. New live events will still appear.",
    )).toBeNull();
  });

  it("centres the primary bound genotype without participant chrome", async () => {
    const multiAgentCall = {
      ...call,
      participants: [
        call.participants[0]!,
        {
          id: "chief",
          label: "Chief of staff",
          kind: "agent" as const,
          familiar_genotype: {
            source: "agent_capability.name.v1" as const,
            seed: 11,
            body: "cassini",
            palette: ["#dbeafe", "#3b82f6", "#172554"],
            markings: ["arc"],
            accessories: [],
          },
        },
        {
          id: "lyell",
          label: "Lyell",
          kind: "agent" as const,
          familiar_genotype: {
            source: "agent_capability.name.v1" as const,
            seed: 22,
            body: "kepler",
            palette: ["#dcfce7", "#22c55e", "#14532d"],
            markings: ["orbit"],
            accessories: ["antenna"],
          },
        },
      ],
    };
    api.createCall.mockResolvedValue({ ...mediaResult, call: multiAgentCall });
    api.callEvents.mockReset().mockResolvedValue({ events: [] });

    render(
      <VoiceCall
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onError={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "◉ Start call" }));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    act(() => {
      FakeWebSocket.instances[0]?.onmessage?.(new MessageEvent("message", {
        data: JSON.stringify({ type: "ready" }),
      }));
    });

    const chief = await screen.findByRole("img", { name: "Familiar · ready" });
    expect(chief.getAttribute("data-familiar-body")).toBe("cassini");
    expect(document.querySelectorAll(".familiar-stage")).toHaveLength(1);
    expect(document.querySelector(".voice-call-participants")).toBeNull();
    expect(screen.queryByRole("button", { name: /Show Lyell/ })).toBeNull();
    expect(api.createCall).toHaveBeenCalledTimes(1);
  });

  it("opens a full-window call surface and mutes the real microphone track", async () => {
    const microphoneTrack = { enabled: true, stop: vi.fn() };
    api.callEvents.mockReset().mockResolvedValue({ events: [] });
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockResolvedValue({
          getAudioTracks: () => [microphoneTrack],
          getTracks: () => [microphoneTrack],
        }),
      },
    });

    render(
      <VoiceCall
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onError={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "◉ Start call" }));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    act(() => {
      FakeWebSocket.instances[0]?.onmessage?.(new MessageEvent("message", {
        data: JSON.stringify({ type: "ready" }),
      }));
    });

    const dialog = await screen.findByRole("dialog", { name: "Voice call" });
    expect(dialog.getAttribute("data-screen-label")).toBe("Call");
    expect(document.body.classList.contains("voice-call-present")).toBe(true);
    expect(screen.getByRole("textbox", { name: "Type a message to the call" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Leave" })).toBeTruthy();
    expect(document.querySelector(".voice-call-title")).toBeNull();
    expect(document.querySelector(".voice-call-participants")).toBeNull();
    expect(document.querySelector(".voice-call-state")).toBeNull();
    expect(screen.queryByRole("button", { name: "Hold everything" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Mute me" }));
    expect(microphoneTrack.enabled).toBe(false);
    expect(screen.getByRole("button", { name: "Unmute me" }).getAttribute(
      "aria-pressed",
    )).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Unmute me" }));
    expect(microphoneTrack.enabled).toBe(true);

    const playbackGain = FakeAudioContext.instances[0]?.gains[1];
    expect(playbackGain?.gain.value).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "Silence Familiar" }));
    expect(playbackGain?.gain.value).toBe(0);
    expect(screen.getByRole("button", { name: "Hear Familiar" }).getAttribute(
      "aria-pressed",
    )).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Hear Familiar" }));
    expect(playbackGain?.gain.value).toBe(1);
  });

  it("keeps the selected Jarvis character on the full-window call Stage", async () => {
    saveCharacterLocal("jarvis");
    api.callEvents.mockReset().mockResolvedValue({ events: [] });
    render(
      <VoiceCall
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onError={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "◉ Start call" }));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    act(() => {
      FakeWebSocket.instances[0]?.onmessage?.(new MessageEvent("message", {
        data: JSON.stringify({ type: "ready" }),
      }));
    });

    await waitFor(() => expect(document.querySelector(".jarvis-stage")).toBeTruthy());
    expect(document.querySelector(".familiar-stage")).toBeNull();
    expect(screen.getByRole("button", { name: "Silence Jarvis" })).toBeTruthy();
  });

  it("sends typed mid-call text over the media socket and shows the echoed line", async () => {
    api.callEvents.mockReset().mockResolvedValue({ events: [] });
    render(
      <VoiceCall
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onError={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "◉ Start call" }));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0]!;
    socket.readyState = FakeWebSocket.OPEN;
    act(() => {
      socket.onmessage?.(new MessageEvent("message", {
        data: JSON.stringify({ type: "ready" }),
      }));
    });

    const composer = await screen.findByRole(
      "textbox",
      { name: "Type a message to the call" },
    );
    fireEvent.change(composer, { target: { value: "got your text?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(socket.send).toHaveBeenCalledWith(
      JSON.stringify({ type: "user_text", text: "got your text?" }),
    );
    expect((composer as HTMLInputElement).value).toBe("");

    // The gateway injects the text into the provider session and echoes it
    // back as a transcript call_event, which renders the visible typed line.
    act(() => {
      socket.onmessage?.(new MessageEvent("message", {
        data: JSON.stringify({
          type: "call_event",
          event: {
            id: "event-typed-1",
            type: "transcript",
            participant_id: "user",
            payload: {
              text: "got your text?",
              final: true,
              kind: "input",
              via: "text",
            },
          },
        }),
      }));
    });
    expect(await screen.findByText((_, element) => (
      element?.tagName === "P" && element.textContent === "You: got your text?"
    ))).toBeTruthy();
  });

  it("does not carry a typed call draft from conversation A into recovered call B", async () => {
    const callB = {
      ...call,
      id: "call-b",
      conversation_id: "conversation-b",
      status: "active" as const,
    };
    api.currentCall.mockImplementation((conversationId: string) => Promise.resolve({
      call: conversationId === "conversation-b" ? callB : null,
    }));
    api.callEvents.mockReset().mockResolvedValue({ events: [] });
    api.reopenCall.mockResolvedValue({
      call: { ...callB, status: "reconnecting" as const },
      media_token: "media-token-b",
      websocket_url: "/voice/v1/calls/call-b/media",
    });
    const view = render(
      <VoiceCall
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onError={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "◉ Start call" }));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socketA = FakeWebSocket.instances[0]!;
    socketA.readyState = FakeWebSocket.OPEN;
    act(() => {
      socketA.onmessage?.(new MessageEvent("message", {
        data: JSON.stringify({ type: "ready" }),
      }));
    });
    const draftA = await screen.findByRole(
      "textbox",
      { name: "Type a message to the call" },
    );
    fireEvent.change(draftA, { target: { value: "conversation A secret" } });

    view.rerender(
      <VoiceCall
        conversationId="conversation-b"
        onConversation={vi.fn()}
        onError={vi.fn()}
      />,
    );
    await waitFor(() => expect(api.currentCall).toHaveBeenCalledWith("conversation-b"));
    fireEvent.click(await screen.findByRole("button", { name: "Resume call" }));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2));
    const socketB = FakeWebSocket.instances[1]!;
    socketB.readyState = FakeWebSocket.OPEN;
    act(() => {
      socketB.onmessage?.(new MessageEvent("message", {
        data: JSON.stringify({ type: "ready" }),
      }));
    });

    const draftB = await screen.findByRole(
      "textbox",
      { name: "Type a message to the call" },
    );
    expect((draftB as HTMLInputElement).value).toBe("");
    expect((screen.getByRole("button", { name: "Send" }) as HTMLButtonElement).disabled).toBe(true);
    expect(socketA.send).not.toHaveBeenCalledWith(expect.stringContaining("conversation A secret"));
    expect(socketB.send).not.toHaveBeenCalledWith(expect.stringContaining("conversation A secret"));

    fireEvent.change(draftB, { target: { value: "conversation B message" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(socketB.send).toHaveBeenCalledWith(
      JSON.stringify({ type: "user_text", text: "conversation B message" }),
    );
  });

  it("makes the full-window call truly modal and restores exact background state on Escape", async () => {
    api.callEvents.mockReset().mockResolvedValue({ events: [] });
    const legacySibling = document.createElement("aside");
    legacySibling.dataset.voiceModalTestSibling = "legacy";
    legacySibling.setAttribute("aria-hidden", "false");
    legacySibling.setAttribute("inert", "legacy");
    document.body.append(legacySibling);

    const rendered = render(<VoiceCallWithPersistentOpener />);
    const opener = screen.getByRole("button", { name: "Open voice call" });
    opener.focus();
    expect(document.activeElement).toBe(opener);
    fireEvent.click(opener);

    const dialog = await screen.findByRole("dialog", { name: "Voice call" });
    expect(document.activeElement).toBe(dialog);
    expect(rendered.container.getAttribute("aria-hidden")).toBe("true");
    expect(rendered.container.hasAttribute("inert")).toBe(true);
    expect(rendered.container.inert).toBe(true);
    expect(legacySibling.getAttribute("aria-hidden")).toBe("true");
    expect(legacySibling.inert).toBe(true);

    const lateSibling = document.createElement("div");
    lateSibling.dataset.voiceModalTestSibling = "late";
    const lateButton = document.createElement("button");
    lateButton.textContent = "Background action";
    lateSibling.append(lateButton);
    document.body.append(lateSibling);
    await waitFor(() => expect(lateSibling.getAttribute("aria-hidden")).toBe("true"));
    expect(lateSibling.inert).toBe(true);

    const leave = screen.getByRole("button", { name: "Leave" });
    const mute = screen.getByRole("button", { name: "Silence Familiar" });
    mute.focus();
    fireEvent.keyDown(mute, { key: "Tab" });
    expect(document.activeElement).toBe(leave);
    leave.focus();
    fireEvent.keyDown(leave, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(mute);
    lateButton.focus();
    expect(document.activeElement).toBe(mute);
    expect(dialog.contains(document.activeElement)).toBe(true);

    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(api.endCall).toHaveBeenCalledWith(call.id));
    expect(await screen.findByText("Call ended")).toBeTruthy();
    expect(document.body.classList.contains("voice-call-present")).toBe(false);

    expect(rendered.container.hasAttribute("aria-hidden")).toBe(false);
    expect(rendered.container.hasAttribute("inert")).toBe(false);
    expect(rendered.container.inert).toBe(false);
    expect(legacySibling.getAttribute("aria-hidden")).toBe("false");
    expect(legacySibling.getAttribute("inert")).toBe("legacy");
    expect(legacySibling.inert).toBe(true);
    expect(lateSibling.hasAttribute("aria-hidden")).toBe(false);
    expect(lateSibling.hasAttribute("inert")).toBe(false);
    expect(lateSibling.inert).toBe(false);
    expect(document.activeElement).toBe(opener);
  });

  it("restores focus to the persistent opener after Leave", async () => {
    api.callEvents.mockReset().mockResolvedValue({ events: [] });
    render(<VoiceCallWithPersistentOpener />);
    const opener = screen.getByRole("button", { name: "Open voice call" });
    opener.focus();
    fireEvent.click(opener);
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));

    fireEvent.click(screen.getByRole("button", { name: "Leave" }));

    expect(await screen.findByText("Call ended")).toBeTruthy();
    expect(document.activeElement).toBe(opener);
  });

  it("restores focus when the active call closes from a live event", async () => {
    api.callEvents.mockReset().mockResolvedValue({ events: [] });
    render(<VoiceCallWithPersistentOpener />);
    const opener = screen.getByRole("button", { name: "Open voice call" });
    opener.focus();
    fireEvent.click(opener);
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    act(() => {
      FakeWebSocket.instances[0]?.onmessage?.(new MessageEvent("message", {
        data: JSON.stringify({ type: "ready" }),
      }));
    });
    expect(await screen.findByText("Live voice")).toBeTruthy();

    act(() => {
      FakeWebSocket.instances[0]?.onmessage?.(new MessageEvent("message", {
        data: JSON.stringify({
          type: "call_event",
          event: {
            id: "event-ended-remotely",
            call_id: call.id,
            type: "ended",
            participant_id: "agent",
            payload: {},
            created_at: "2026-07-29T10:05:00Z",
          },
        }),
      }));
    });

    expect(await screen.findByText("Call ended")).toBeTruthy();
    expect(api.endCall).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(opener);
  });

  it("keeps the newly created call connected while adopting its conversation", async () => {
    const stopTrack = vi.fn();
    api.callEvents.mockReset().mockResolvedValue({ events: [] });
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockResolvedValue({
          getTracks: () => [{ stop: stopTrack }],
        }),
      },
    });
    function ConversationHarness() {
      const [conversationId, setConversationId] = useState<string | null>(null);
      return (
        <VoiceCall
          conversationId={conversationId}
          onConversation={setConversationId}
          onError={vi.fn()}
        />
      );
    }

    render(<ConversationHarness />);
    fireEvent.click(screen.getByRole("button", { name: "◉ Start call" }));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    act(() => {
      FakeWebSocket.instances[0]?.onmessage?.(new MessageEvent("message", {
        data: JSON.stringify({ type: "ready" }),
      }));
    });

    expect(await screen.findByText("Live voice")).toBeTruthy();
    expect(stopTrack).not.toHaveBeenCalled();
    expect(FakeWebSocket.instances[0]?.close).not.toHaveBeenCalled();
  });

  it("releases media and explains a bounded-capacity refusal", async () => {
    const onError = vi.fn();
    const stop = vi.fn();
    const closeContext = vi.fn().mockResolvedValue(undefined);
    api.callEvents.mockReset().mockResolvedValue({ events: [] });
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockResolvedValue({
          getTracks: () => [{ stop }],
        }),
      },
    });
    vi.stubGlobal("AudioContext", class extends FakeAudioContext {
      close = closeContext;
    });

    render(
      <VoiceCall
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onError={onError}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "◉ Start call" }));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));

    act(() => {
      FakeWebSocket.instances[0]?.onclose?.(
        new CloseEvent("close", { code: 4429, reason: "capacity" }),
      );
    });

    expect(await screen.findByText("Call interrupted")).toBeTruthy();
    expect(onError).toHaveBeenLastCalledWith(expect.stringContaining("at capacity"));
    expect(stop).toHaveBeenCalledOnce();
    expect(closeContext).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Reconnect" })).toBeTruthy();
  });

  it("restores history, exposes held/resumed state, and retains transcript after end", async () => {
    render(
      <VoiceCall
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onError={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "◉ Start call" }));
    await waitFor(() => expect(api.callEvents).toHaveBeenCalledWith(call.id));
    expect(await screen.findByText("Waiting for approval")).toBeTruthy();
    expect(screen.getByRole("dialog", { name: "Voice call" }).getAttribute(
      "data-screen-label",
    )).toBe("Call");
    expect(screen.getByText(
      "Approval needed for ticket.create. Review it in the originating chat to continue.",
    ).closest("article")?.getAttribute("data-urgent")).toBe("true");
    expect(screen.getByText("Earlier question")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Open Inbox" })).toBeNull();

    act(() => {
      FakeWebSocket.instances[0]?.onclose?.(new CloseEvent("close"));
    });
    fireEvent.click(await screen.findByRole("button", { name: "Reconnect" }));

    await waitFor(() => expect(api.callEvents).toHaveBeenCalledTimes(2));
    expect(await screen.findByText(
      "Approval granted. Voice will resume when the connection is ready.",
    )).toBeTruthy();
    expect(screen.getByText("Continuing now")).toBeTruthy();
    expect(screen.getByText("Joining…")).toBeTruthy();
    act(() => {
      FakeWebSocket.instances[1]?.onmessage?.(new MessageEvent("message", {
        data: JSON.stringify({ type: "ready" }),
      }));
    });
    expect(screen.getByText("Live voice")).toBeTruthy();
    expect(screen.getByText("Approval granted. Voice resumed.")).toBeTruthy();
    expect(screen.getAllByText("Earlier question")).toHaveLength(1);

    act(() => {
      FakeWebSocket.instances[1]?.onmessage?.(new MessageEvent("message", {
        data: JSON.stringify({
          type: "call_event",
          event: {
            id: "event-reconnected",
            call_id: call.id,
            type: "reconnected",
            payload: { reason: "provider_reconnected" },
            created_at: "2026-07-29T10:00:04Z",
          },
        }),
      }));
    });
    expect(await screen.findByText("Voice reconnected.")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Leave" }));
    expect(await screen.findByText("Call ended")).toBeTruthy();
    expect(screen.getByText("Earlier question")).toBeTruthy();
    expect(screen.getByText("Continuing now")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Start another call" })).toBeTruthy();
  });

  it("shows bounded recent calls and only resumes recoverable sessions", async () => {
    api.calls.mockResolvedValue({
      calls: [
        {
          ...call,
          id: "call-recoverable",
          agent_profile_id: "research-familiar",
          model_profile_id: "voice-fast",
          status: "reconnecting",
          created_at: "2026-07-29T09:00:00Z",
          updated_at: "2026-07-29T10:06:00Z",
        },
        {
          ...call,
          id: "call-terminal",
          agent_profile_id: "default-familiar",
          model_profile_id: "voice-balanced",
          status: "ended",
          created_at: "2026-07-29T08:00:00Z",
          updated_at: "2026-07-29T08:05:00Z",
          ended_at: "2026-07-29T08:05:00Z",
        },
      ],
    });

    render(
      <VoiceCall
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onError={vi.fn()}
      />,
    );

    await waitFor(() => expect(api.calls).toHaveBeenCalledWith(10));
    fireEvent.click(screen.getByText("Recent calls · 2"));
    expect(screen.getByText(/Agent: research-familiar/)).toBeTruthy();
    expect(screen.getByText(/Model: voice-fast/)).toBeTruthy();
    expect(screen.getByText(/Agent: default-familiar/)).toBeTruthy();
    expect(screen.getByText(/Model: voice-balanced/)).toBeTruthy();
    expect(document.querySelector('time[datetime="2026-07-29T10:06:00Z"]')).toBeTruthy();
    expect(document.querySelector('time[datetime="2026-07-29T08:05:00Z"]')).toBeTruthy();
    expect(screen.queryByRole("button", {
      name: "Resume recent call call-terminal",
    })).toBeNull();

    fireEvent.click(screen.getByRole("button", {
      name: "Resume recent call call-recoverable",
    }));
    await waitFor(() => expect(api.reopenCall).toHaveBeenCalledWith("call-recoverable"));
  });

  it("releases every acquired media resource when authentication setup fails", async () => {
    const onError = vi.fn();
    const stopTrack = vi.fn();
    api.callEvents.mockReset().mockResolvedValue({ events: [] });
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockResolvedValue({
          getTracks: () => [{ stop: stopTrack }],
        }),
      },
    });

    render(
      <VoiceCall
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onError={onError}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "◉ Start call" }));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    FakeWebSocket.instances[0]!.send.mockImplementation(() => {
      throw new Error("send failed");
    });

    act(() => {
      FakeWebSocket.instances[0]?.onopen?.(new Event("open"));
    });

    expect(await screen.findByText("Call interrupted")).toBeTruthy();
    expect(onError).toHaveBeenLastCalledWith(expect.stringContaining("authenticated"));
    expect(stopTrack).toHaveBeenCalledOnce();
    expect(FakeAudioContext.instances[0]?.close).toHaveBeenCalledOnce();
    expect(FakeWebSocket.instances[0]?.close).toHaveBeenCalledWith(
      1000,
      "client closed",
    );
  });

  it("stops a late microphone stream when setup is cancelled during acquisition", async () => {
    api.callEvents.mockReset().mockResolvedValue({ events: [] });
    const stopTrack = vi.fn();
    let resolveStream!: (stream: { getTracks(): Array<{ stop(): void }> }) => void;
    const pendingStream = new Promise<{ getTracks(): Array<{ stop(): void }> }>(
      (resolve) => {
        resolveStream = resolve;
      },
    );
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockReturnValue(pendingStream),
      },
    });
    const rendered = render(
      <VoiceCall
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onError={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "◉ Start call" }));
    await waitFor(() => expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalled());

    rendered.unmount();
    await act(async () => {
      resolveStream({ getTracks: () => [{ stop: stopTrack }] });
      await pendingStream;
      await Promise.resolve();
    });

    expect(stopTrack).toHaveBeenCalledOnce();
    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("times out a socket that never becomes authenticated and reports released media", async () => {
    vi.useFakeTimers();
    const onError = vi.fn();
    const stopTrack = vi.fn();
    api.callEvents.mockReset().mockResolvedValue({ events: [] });
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockResolvedValue({
          getTracks: () => [{ stop: stopTrack }],
        }),
      },
    });

    try {
      render(
        <VoiceCall
          conversationId="conversation-a"
          onConversation={vi.fn()}
          onError={onError}
        />,
      );
      fireEvent.click(screen.getByRole("button", { name: "◉ Start call" }));
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(FakeWebSocket.instances).toHaveLength(1);
      const captureAnalyser = FakeAudioContext.instances[0]?.analysers[0];
      if (captureAnalyser) {
        delete (captureAnalyser as Partial<typeof captureAnalyser>)
          .getFloatTimeDomainData;
      }

      await act(async () => {
        await vi.advanceTimersByTimeAsync(15_000);
      });

      expect(screen.getByText("Call interrupted")).toBeTruthy();
      expect(onError).toHaveBeenLastCalledWith(expect.stringContaining(
        "did not become ready in time",
      ));
      expect(stopTrack).toHaveBeenCalledOnce();
      expect(FakeAudioContext.instances[0]?.close).toHaveBeenCalledOnce();
      expect(FakeWebSocket.instances[0]?.close).toHaveBeenCalledOnce();
    } finally {
      vi.useRealTimers();
    }
  });

  it("still reports a dropped socket after reconnecting from a failed end", async () => {
    const onError = vi.fn();
    api.callEvents.mockReset().mockResolvedValue({ events: [] });
    api.endCall.mockRejectedValueOnce(new Error("The call could not be ended."));

    render(
      <VoiceCall
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onError={onError}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "◉ Start call" }));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    act(() => {
      FakeWebSocket.instances[0]?.onmessage?.(new MessageEvent("message", {
        data: JSON.stringify({ type: "ready" }),
      }));
    });
    expect(await screen.findByText("Live voice")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Leave" }));
    expect(await screen.findByText("Call interrupted")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Reconnect" }));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2));
    act(() => {
      FakeWebSocket.instances[1]?.onmessage?.(new MessageEvent("message", {
        data: JSON.stringify({ type: "ready" }),
      }));
    });
    expect(await screen.findByText("Live voice")).toBeTruthy();

    act(() => {
      FakeWebSocket.instances[1]?.onclose?.(new CloseEvent("close"));
    });

    expect(await screen.findByText("Connection paused")).toBeTruthy();
    expect(onError).toHaveBeenLastCalledWith(
      expect.stringContaining("connection closed"),
    );
    expect(screen.getByRole("button", { name: "Reconnect" })).toBeTruthy();
  });

  it("dials the relative gateway URL on the document origin in the browser", async () => {
    api.callEvents.mockReset().mockResolvedValue({ events: [] });
    render(
      <VoiceCall
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onError={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "◉ Start call" }));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));

    expect(FakeWebSocket.instances[0]?.url).toBe(
      `ws://${window.location.host}/voice/v1/calls/call-a/media`,
    );
  });

  it("dials the configured API origin from the desktop shell, not its webview", async () => {
    native.isDesktop = true;
    vi.stubEnv("VITE_API_BASE", "https://kernel.boltrig.test/");
    api.callEvents.mockReset().mockResolvedValue({ events: [] });
    render(
      <VoiceCall
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onError={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "◉ Start call" }));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));

    expect(FakeWebSocket.instances[0]?.url).toBe(
      "wss://kernel.boltrig.test/voice/v1/calls/call-a/media",
    );
  });

  it("stops queued playback on interruption and resets scheduling for a new context", async () => {
    api.callEvents.mockReset().mockResolvedValue({ events: [] });
    FakeAudioContext.nextCurrentTimes = [10, 2];
    render(
      <VoiceCall
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onError={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "◉ Start call" }));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    act(() => {
      FakeWebSocket.instances[0]?.onmessage?.(new MessageEvent("message", {
        data: JSON.stringify({ type: "ready" }),
      }));
      FakeWebSocket.instances[0]?.onmessage?.(new MessageEvent("message", {
        data: new Int16Array([100, 200]).buffer,
      }));
      FakeWebSocket.instances[0]?.onmessage?.(new MessageEvent("message", {
        data: new Int16Array([300, 400]).buffer,
      }));
    });

    const firstContext = FakeAudioContext.instances[0]!;
    expect(firstContext.playbackSources[0]?.start).toHaveBeenCalledWith(10);
    expect(firstContext.playbackSources[1]?.start).toHaveBeenCalledWith(11);

    act(() => {
      FakeWebSocket.instances[0]?.onmessage?.(new MessageEvent("message", {
        data: JSON.stringify({
          type: "call_event",
          event: {
            type: "interrupted",
            payload: { reason: "barge_in" },
          },
        }),
      }));
    });
    expect(await screen.findByText("Playback stopped while you were speaking."))
      .toBeTruthy();
    expect(firstContext.playbackSources[0]?.stop).toHaveBeenCalledOnce();
    expect(firstContext.playbackSources[1]?.stop).toHaveBeenCalledOnce();

    act(() => {
      FakeWebSocket.instances[0]?.onclose?.(new CloseEvent("close"));
    });
    fireEvent.click(await screen.findByRole("button", { name: "Reconnect" }));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2));
    act(() => {
      FakeWebSocket.instances[1]?.onmessage?.(new MessageEvent("message", {
        data: JSON.stringify({ type: "ready" }),
      }));
      FakeWebSocket.instances[1]?.onmessage?.(new MessageEvent("message", {
        data: new Int16Array([500, 600]).buffer,
      }));
    });

    const secondContext = FakeAudioContext.instances[1]!;
    expect(secondContext.playbackSources[0]?.start).toHaveBeenCalledWith(2);
  });

  it("barges in from the microphone and drops the turn that keeps arriving", async () => {
    // The provider's own VAD is not involved here: no `interrupted` event is
    // ever delivered. Everything below is the client-side energy gate.
    api.callEvents.mockReset().mockResolvedValue({ events: [] });
    vi.stubEnv("VITE_SELF_HOSTED_TTS_ORIGIN", "http://127.0.0.1:8911");
    const fetchMock = vi.fn().mockResolvedValue(new Response(null));
    vi.stubGlobal("fetch", fetchMock);
    vi.useFakeTimers();

    render(
      <VoiceCall
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onError={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "◉ Start call" }));
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });

    const socket = FakeWebSocket.instances[0]!;
    const context = FakeAudioContext.instances[0]!;
    // The capture-side gate reads 512 samples; the playback analyser is 1024.
    const microphone = context.analysers.find((node) => node.fftSize === 512)!;
    expect(microphone).toBeTruthy();

    act(() => {
      socket.onmessage?.(new MessageEvent("message", {
        data: JSON.stringify({ type: "ready" }),
      }));
    });

    // ~ -61 dBFS of room noise, the floor measured on this estate's captures.
    microphone.micLevel = 0.000_9;
    await act(async () => { await vi.advanceTimersByTimeAsync(800); });

    act(() => {
      socket.onmessage?.(new MessageEvent("message", {
        data: new Int16Array([100, 200]).buffer,
      }));
    });
    expect(context.playbackSources).toHaveLength(1);
    // Let the echo tracker settle against a turn that is leaking nothing.
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    expect(context.playbackSources[0]?.stop).not.toHaveBeenCalled();

    // ~ -26 dBFS: the median voiced frame in those same captures.
    microphone.micLevel = 0.05;
    await act(async () => { await vi.advanceTimersByTimeAsync(50); });

    expect(context.playbackSources[0]?.stop).toHaveBeenCalledOnce();
    expect(screen.getByText("Playback stopped while you were speaking.")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8911/interrupt",
      { method: "POST" },
    );

    // The provider has not stopped generating yet, so the rest of the turn is
    // discarded rather than scheduled behind the audio just stopped.
    act(() => {
      socket.onmessage?.(new MessageEvent("message", {
        data: new Int16Array([300, 400]).buffer,
      }));
    });
    expect(context.playbackSources).toHaveLength(1);

    // The microphone keeps streaming throughout, so the transcript follows the
    // interrupt rather than gating it.
    act(() => {
      socket.onmessage?.(new MessageEvent("message", {
        data: JSON.stringify({
          type: "call_event",
          event: {
            id: "event-late-transcript",
            type: "transcript",
            payload: { text: "wait, stop", final: true, kind: "input" },
          },
        }),
      }));
    });
    expect(screen.getByText("wait, stop")).toBeTruthy();
  });

  it("does not barge in on the companion's own voice leaking past the canceller", async () => {
    api.callEvents.mockReset().mockResolvedValue({ events: [] });
    vi.useFakeTimers();

    render(
      <VoiceCall
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onError={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "◉ Start call" }));
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });

    const socket = FakeWebSocket.instances[0]!;
    const context = FakeAudioContext.instances[0]!;
    const microphone = context.analysers.find((node) => node.fftSize === 512)!;

    act(() => {
      socket.onmessage?.(new MessageEvent("message", {
        data: JSON.stringify({ type: "ready" }),
      }));
    });
    microphone.micLevel = 0.000_9;
    await act(async () => { await vi.advanceTimersByTimeAsync(800); });

    act(() => {
      socket.onmessage?.(new MessageEvent("message", {
        data: new Int16Array([100, 200]).buffer,
      }));
    });
    // An open speaker leaking 27dB over the room floor for the whole turn. AEC3
    // should have removed it; the gate must not fire even when it has not.
    microphone.micLevel = 0.02;
    await act(async () => { await vi.advanceTimersByTimeAsync(3_000); });

    expect(context.playbackSources[0]?.stop).not.toHaveBeenCalled();
    expect(screen.queryByText("Playback stopped while you were speaking.")).toBeNull();
  });
});
