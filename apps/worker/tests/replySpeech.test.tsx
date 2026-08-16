// @vitest-environment happy-dom

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  capabilities: vi.fn(),
  invoke: vi.fn(),
  meSettings: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { saveCharacterLocal } from "../src/character";
import { speechText, useReplySpeech } from "../src/components/chat/useReplySpeech";

class FakeAudioSource {
  buffer: unknown = null;
  onended: (() => void) | null = null;
  connect = vi.fn();
  disconnect = vi.fn();
  start = vi.fn();
  stop = vi.fn();
}

class FakeGainNode {
  gain = { value: 1 };
  connect = vi.fn();
  disconnect = vi.fn();
}

/** Decoded audio at a known level, so the applied gain has a right answer. */
function fakeBuffer(rmsDbfs: number, samples = 24_000): AudioBuffer {
  const amplitude = 10 ** (rmsDbfs / 20) * Math.SQRT2;
  const data = new Float32Array(samples);
  for (let i = 0; i < samples; i += 1) {
    data[i] = amplitude * Math.sin((2 * Math.PI * 200 * i) / 24_000);
  }
  return { getChannelData: () => data } as unknown as AudioBuffer;
}

class FakeAudioContext {
  static instances: FakeAudioContext[] = [];
  state: AudioContextState = "running";
  destination = {} as AudioDestinationNode;
  sources: FakeAudioSource[] = [];
  gains: FakeGainNode[] = [];
  close = vi.fn().mockResolvedValue(undefined);
  resume = vi.fn().mockResolvedValue(undefined);
  // A real buffer, not `{}`: playback normalises from the decoded samples, so
  // a double that returns an empty object models an AudioBuffer that cannot
  // exist and hides the behaviour under test.
  decodeAudioData = vi.fn().mockResolvedValue(fakeBuffer(-26));
  createBufferSource = vi.fn(() => {
    const source = new FakeAudioSource();
    this.sources.push(source);
    return source;
  });
  createGain = vi.fn(() => {
    const gain = new FakeGainNode();
    this.gains.push(gain);
    return gain;
  });

  constructor() {
    FakeAudioContext.instances.push(this);
  }
}

function Harness() {
  const [activity, setActivity] = useState("none");
  const [errorCount, setErrorCount] = useState(0);
  const speech = useReplySpeech({
    conversationKey: "conversation-a",
    onActivity: (next) => setActivity(next.speaking ? "speaking" : "quiet"),
    onError: () => setErrorCount((count) => count + 1),
  });
  return (
    <>
      <output data-testid="speech-state">
        {speech.loaded ? "loaded" : "loading"}:{speech.enabled ? "on" : "off"}:{speech.provider}
      </output>
      <button onClick={speech.prime} type="button">Prime audio</button>
      <button
        onClick={() => void speech.readReply("run-a", "Hello **there**")}
        type="button"
      >Read reply</button>
      <output data-testid="activity">{activity}</output>
      <output data-testid="error-count">{errorCount}</output>
    </>
  );
}

beforeEach(() => {
  localStorage.clear();
  FakeAudioContext.instances = [];
  vi.stubGlobal("AudioContext", FakeAudioContext);
  api.meSettings.mockResolvedValue({
    profile: { id: "user-a" },
    settings: { "voice.read_replies": true },
  });
  api.capabilities.mockResolvedValue({
    verbs: [{
      id: "voice.speak",
      binding: { target_type: "adapter", target_ref: "pocket-voice" },
    }],
  });
  api.invoke.mockResolvedValue({
    status: "ok",
    output: { audio_b64: btoa("audio"), content_type: "audio/wav" },
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("reply speech", () => {
  it("uses Familiar's declared local voice and animates only during playback", async () => {
    render(<Harness />);
    await waitFor(() => expect(screen.getByTestId("speech-state").textContent)
      .toBe("loaded:on:pocket-voice"));

    fireEvent.click(screen.getByRole("button", { name: "Prime audio" }));
    fireEvent.click(screen.getByRole("button", { name: "Read reply" }));

    await waitFor(() => expect(api.invoke).toHaveBeenCalledWith({
      noun: "voice",
      verb: "voice.speak",
      params: { text: "Hello there", voice: "vera" },
    }));
    await waitFor(() => expect(FakeAudioContext.instances[0]?.sources[0]?.start)
      .toHaveBeenCalledOnce());
    expect(screen.getByTestId("activity").textContent).toBe("speaking");


    // The reply is normalised on the way out, not by the provider. -26 dBFS of
    // speech needs +10 dB to reach the -16 target, so the gain must be ~3.16x
    // and must sit between the source and the destination.
    const gain = FakeAudioContext.instances[0]?.gains[0];
    expect(gain).toBeDefined();
    expect(20 * Math.log10(gain?.gain.value ?? 1)).toBeCloseTo(10, 1);
    expect(FakeAudioContext.instances[0]?.sources[0]?.connect)
      .toHaveBeenCalledWith(gain);
    act(() => FakeAudioContext.instances[0]?.sources[0]?.onended?.());
    expect(screen.getByTestId("activity").textContent).toBe("quiet");
    expect(screen.getByTestId("error-count").textContent).toBe("0");
  });

  it("uses Jarvis's own voice rather than borrowing Familiar's", async () => {
    saveCharacterLocal("jarvis");
    render(<Harness />);
    await waitFor(() => expect(screen.getByTestId("speech-state").textContent)
      .toBe("loaded:on:pocket-voice"));
    fireEvent.click(screen.getByRole("button", { name: "Read reply" }));
    await waitFor(() => expect(api.invoke).toHaveBeenCalledWith(expect.objectContaining({
      params: { text: "Hello there", voice: "jarvis" },
    })));
  });

  it("does not call a provider until the user opts in", async () => {
    api.meSettings.mockResolvedValue({
      profile: { id: "user-a" },
      settings: { "voice.read_replies": false },
    });
    render(<Harness />);
    await waitFor(() => expect(screen.getByTestId("speech-state").textContent)
      .toBe("loaded:off:pocket-voice"));
    fireEvent.click(screen.getByRole("button", { name: "Read reply" }));
    expect(api.invoke).not.toHaveBeenCalled();
  });

  it("removes code and link destinations from spoken markdown", () => {
    expect(speechText("# Result\n[Open](https://example.test) `now`\n```sh\nsecret\n```"))
      .toBe("Result Open now Code omitted.");
  });
});
