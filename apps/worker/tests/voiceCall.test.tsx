// @vitest-environment happy-dom

import { useState } from "react";
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
  createMediaStreamSource = vi.fn(() => new FakeAudioNode());
  createScriptProcessor = vi.fn(() => Object.assign(new FakeAudioNode(), {
    onaudioprocess: null,
  }));
  createGain = vi.fn(() => Object.assign(new FakeAudioNode(), {
    gain: { value: 1 },
  }));
  createAnalyser = vi.fn(() => Object.assign(new FakeAudioNode(), {
    fftSize: 0,
    smoothingTimeConstant: 0,
    frequencyBinCount: 512,
    getByteFrequencyData: vi.fn(),
  }));
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
  vi.clearAllMocks();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("Worker realtime voice continuity", () => {
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
    expect(screen.getByText("Earlier question")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open Inbox" }).getAttribute("href"))
      .toBe("#/inbox");

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

    fireEvent.click(screen.getByRole("button", { name: "End" }));
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

    fireEvent.click(screen.getByRole("button", { name: "End" }));
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
});
