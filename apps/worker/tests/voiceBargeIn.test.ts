import { afterEach, describe, expect, it, vi } from "vitest";

import {
  BARGE_IN_FRAME_MS,
  BARGE_IN_MIN_RMS,
  BARGE_IN_TRIGGER_FRAMES,
  createBargeInGate,
  frameRms,
  type BargeInGate,
} from "../src/components/voiceBargeIn";
import {
  configuredSelfHostedTtsOrigin,
  requestSelfHostedInterrupt,
} from "../src/components/voiceBargeInGraph";

// Amplitudes taken from real 10ms-frame RMS measurements on this estate's own
// barge-in captures (2026-08-13): inter-word floors ran -59 to -61 dBFS and
// voiced speech ran -26 dBFS median, +35 to +39 dB over the preceding floor.
const ROOM_FLOOR = 0.000_9; // ~ -61 dBFS
const SPEECH = 0.05; // ~ -26 dBFS
const LOUD_ECHO_RESIDUAL = 0.02; // ~ -34 dBFS, a deliberately bad open speaker

interface Run {
  triggers: number[];
  lastActive: boolean;
}

/** Feed `frames` identical 10ms frames and report when the gate tripped. */
function feed(
  gate: BargeInGate,
  { rms, playing, frames, from = 0 }: {
    rms: number;
    playing: boolean;
    frames: number;
    from?: number;
  },
): Run {
  const triggers: number[] = [];
  let lastActive = false;
  for (let index = 0; index < frames; index += 1) {
    const now = from + index * BARGE_IN_FRAME_MS;
    const verdict = gate.observe({ rms, playing, now });
    lastActive = verdict.active;
    if (verdict.trigger) triggers.push(now);
  }
  return { triggers, lastActive };
}

/** Warm the room floor, then start a spoken turn and let its echo settle. */
function readyGate(residual = ROOM_FLOOR): { gate: BargeInGate; clock: number } {
  const gate = createBargeInGate();
  feed(gate, { rms: ROOM_FLOOR, playing: false, frames: 80 });
  feed(gate, { rms: residual, playing: true, frames: 40, from: 800 });
  return { gate, clock: 1_200 };
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("barge-in energy gate", () => {
  it("trips on the third consecutive frame of speech over playback", () => {
    const { gate, clock } = readyGate();
    const run = feed(gate, { rms: SPEECH, playing: true, frames: 3, from: clock });
    expect(run.triggers).toEqual([clock + (BARGE_IN_TRIGGER_FRAMES - 1) * BARGE_IN_FRAME_MS]);
  });

  it("never fires when the companion is not speaking", () => {
    const gate = createBargeInGate();
    feed(gate, { rms: ROOM_FLOOR, playing: false, frames: 80 });
    // The user talking into silence is not a barge-in; it is just talking.
    const run = feed(gate, { rms: SPEECH, playing: false, frames: 200, from: 800 });
    expect(run.triggers).toEqual([]);
  });

  it("ignores a single-frame transient", () => {
    const { gate, clock } = readyGate();
    let triggered = false;
    for (let index = 0; index < 40; index += 1) {
      // A key click every fourth frame: loud, but never sustained.
      const rms = index % 4 === 0 ? 0.5 : ROOM_FLOOR;
      const verdict = gate.observe({
        rms,
        playing: true,
        now: clock + index * BARGE_IN_FRAME_MS,
      });
      triggered ||= verdict.trigger;
    }
    expect(triggered).toBe(false);
  });

  it("stays deaf to steady echo leakage but still hears the user over it", () => {
    // The self-trigger guard, on the case AEC3 handles worst: an open speaker
    // whose residual sits 27dB above the room floor.
    const { gate, clock } = readyGate(LOUD_ECHO_RESIDUAL);
    const leak = feed(gate, {
      rms: LOUD_ECHO_RESIDUAL,
      playing: true,
      frames: 300,
      from: clock,
    });
    expect(leak.triggers).toEqual([]);

    // The user's own voice reaches the microphone uncancelled, on top of it.
    const spoken = feed(gate, {
      rms: LOUD_ECHO_RESIDUAL + SPEECH * 4,
      playing: true,
      frames: 5,
      from: clock + 3_000,
    });
    expect(spoken.triggers.length).toBe(1);
  });

  it("cannot fire inside the settling window at the start of a turn", () => {
    const gate = createBargeInGate();
    feed(gate, { rms: ROOM_FLOOR, playing: false, frames: 80 });
    // Speech from the very first frame of playback: still ignored, because the
    // echo tracker has nothing trustworthy to compare it against yet.
    const run = feed(gate, { rms: SPEECH, playing: true, frames: 20, from: 800 });
    expect(run.triggers).toEqual([]);
  });

  it("holds off a second interrupt for the cooldown", () => {
    const { gate, clock } = readyGate();
    const run = feed(gate, { rms: SPEECH, playing: true, frames: 120, from: clock });
    expect(run.triggers.length).toBeGreaterThan(1);
    for (let index = 1; index < run.triggers.length; index += 1) {
      expect(run.triggers[index]! - run.triggers[index - 1]!).toBeGreaterThanOrEqual(400);
    }
  });

  it("keeps reporting the user as active through a long utterance", () => {
    // The drop window is refreshed off `active`, so a floor that crept up into
    // sustained speech would reopen playback while the user was still talking.
    const { gate, clock } = readyGate();
    const run = feed(gate, { rms: SPEECH, playing: true, frames: 400, from: clock });
    expect(run.lastActive).toBe(true);
  });

  it("does not fire on a numerically tiny blip in a digitally silent room", () => {
    const gate = createBargeInGate();
    feed(gate, { rms: 0, playing: false, frames: 80 });
    feed(gate, { rms: 0, playing: true, frames: 40, from: 800 });
    const run = feed(gate, {
      rms: BARGE_IN_MIN_RMS / 2,
      playing: true,
      frames: 100,
      from: 1_200,
    });
    expect(run.triggers).toEqual([]);
  });
});

describe("frameRms", () => {
  it("is zero for an empty or silent frame", () => {
    expect(frameRms(new Float32Array(0))).toBe(0);
    expect(frameRms(new Float32Array(512))).toBe(0);
  });

  it("returns the root-mean-square amplitude", () => {
    expect(frameRms(new Float32Array([0.5, -0.5, 0.5, -0.5]))).toBeCloseTo(0.5, 6);
    expect(frameRms(new Float32Array([1, 0, -1, 0]))).toBeCloseTo(Math.SQRT1_2, 6);
  });
});

describe("self-hosted TTS interrupt", () => {
  it("is absent unless configured, and never guesses a local port", () => {
    vi.stubEnv("VITE_SELF_HOSTED_TTS_ORIGIN", "");
    expect(configuredSelfHostedTtsOrigin()).toBeNull();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    requestSelfHostedInterrupt();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refuses a value that is not a plain http origin", () => {
    for (const value of ["not a url", "file:///etc/passwd", "http://a:b@127.0.0.1:8911"]) {
      vi.stubEnv("VITE_SELF_HOSTED_TTS_ORIGIN", value);
      expect(configuredSelfHostedTtsOrigin()).toBeNull();
    }
  });

  it("posts /interrupt on the configured origin and swallows its failure", () => {
    vi.stubEnv("VITE_SELF_HOSTED_TTS_ORIGIN", "http://127.0.0.1:8911/");
    expect(configuredSelfHostedTtsOrigin()).toBe("http://127.0.0.1:8911");
    const fetchMock = vi.fn().mockRejectedValue(new Error("blocked by CSP"));
    vi.stubGlobal("fetch", fetchMock);
    expect(() => requestSelfHostedInterrupt()).not.toThrow();
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8911/interrupt",
      { method: "POST" },
    );
  });
});
