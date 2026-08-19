// @vitest-environment happy-dom
//
// The microphone meter: the number that reaches a body on the Stage while the
// person in the room is talking.
//
// IT HAS NEVER EXISTED BEFORE, which is the point of testing it now. Every
// character declared `micLevel` on the shared turn input, Jarvis and Ultron both
// read it, and nothing in the tree ever produced one -- so the listening
// animations were driving on a constant zero and looked, correctly, like
// nothing. The gate was already reading the microphone every 10ms and already
// tracking what silence sounds like in this room; the meter is that work, said
// out loud.

import { describe, expect, it, vi } from "vitest";

import {
  BARGE_IN_FRAME_MS,
  BARGE_IN_MIN_RMS,
  BARGE_IN_WARMUP_FRAMES,
  createBargeInGate,
} from "../src/components/voiceBargeIn";
import { bargeInHostFields, startBargeInGate, stopBargeInGate } from "../src/components/voiceBargeInGraph";

/** Run `frames` quiet frames so the floor tracker has something to track. */
function warm(gate: ReturnType<typeof createBargeInGate>, rms: number, frames: number) {
  let now = 0;
  let last = { trigger: false, active: false, level: 0 };
  for (let i = 0; i < frames; i += 1) {
    now += BARGE_IN_FRAME_MS;
    last = gate.observe({ rms, playing: false, now });
  }
  return last;
}

describe("the barge-in gate's level meter", () => {
  it("reads silence as zero and real speech as full scale", () => {
    const floor = 0.001;              // a quiet room, below the absolute anchor
    const gate = createBargeInGate();
    expect(warm(gate, floor, BARGE_IN_WARMUP_FRAMES).level).toBe(0);

    // +35dB over the floor is what the two real captures measured for the first
    // voiced frame of speech, so this is where the meter should be at the top.
    const speech = gate.observe({
      rms: BARGE_IN_MIN_RMS * 10 ** (35 / 20),
      playing: false,
      now: 10_000,
    });
    expect(speech.level).toBeGreaterThan(0.9);
    expect(speech.active).toBe(true);
  });

  it("is relative to the floor, so a loud room is not a loud person", () => {
    const quiet = createBargeInGate();
    const noisy = createBargeInGate();
    warm(quiet, 0.002, BARGE_IN_WARMUP_FRAMES);
    warm(noisy, 0.02, BARGE_IN_WARMUP_FRAMES);
    // The SAME absolute sample: near the top of the meter in a quiet room, and
    // barely off the bottom in a room whose own floor is already there. An
    // absolute meter would read one person as ten times the other.
    const sample = 0.05;
    const inQuiet = quiet.observe({ rms: sample, playing: false, now: 9_000 }).level;
    const inNoise = noisy.observe({ rms: sample, playing: false, now: 9_000 }).level;
    expect(inQuiet).toBeGreaterThan(inNoise * 1.5);
  });

  it("never reads below zero when a frame is quieter than the floor", () => {
    const gate = createBargeInGate();
    warm(gate, 0.02, BARGE_IN_WARMUP_FRAMES);
    expect(gate.observe({ rms: 0.0001, playing: false, now: 9_000 }).level).toBe(0);
    expect(gate.observe({ rms: 0, playing: false, now: 9_100 }).level).toBe(0);
  });
});

describe("what reaches the body", () => {
  /** A capture analyser reading whatever the test currently says the room is.
   *
   * A CONSTANT tone would be the wrong fixture, and instructively so: the floor
   * tracker climbs to meet anything sustained, because anything sustained IS
   * the room. So the level of a constant tone correctly decays to zero, and a
   * test built on one measures nothing.
   */
  function fakeMic(read: () => number) {
    return {
      fftSize: 512,
      getFloatTimeDomainData: (frame: Float32Array) => frame.fill(read()),
    } as unknown as AnalyserNode;
  }

  function host(read: () => number, onMicLevel: (level: number) => void) {
    // The spread FIRST: bargeInHostFields already answers for the two counters,
    // and listing them after it would silently overwrite whatever it decided.
    return {
      ...bargeInHostFields(fakeMic(read), () => undefined, undefined, onMicLevel),
      playbackSources: new Set<AudioBufferSourceNode>(),
    };
  }

  /** Quiet long enough for the floor to settle, then a voice that keeps rising
   *  so the level genuinely moves and every publish is a real change. */
  function rising() {
    let frame = 0;
    return () => {
      frame += 1;
      return frame < 60 ? 0.001 : Math.min(0.4, 0.004 * (frame - 58));
    };
  }

  it("publishes at ~30Hz rather than at the gate's 100Hz poll", () => {
    vi.useFakeTimers();
    const seen: number[] = [];
    const media = host(rising(), (level) => seen.push(level));
    startBargeInGate(media, () => false);
    vi.advanceTimersByTime(600);        // the quiet phase: floor settles
    seen.length = 0;
    // One second of polling is a hundred gate frames. A React state update per
    // frame would spend the whole saving the analyser is polled quickly to make.
    vi.advanceTimersByTime(1000);
    stopBargeInGate(media);
    vi.useRealTimers();
    expect(seen.length).toBeGreaterThan(5);
    expect(seen.length).toBeLessThanOrEqual(31);
    expect(Math.max(...seen)).toBeGreaterThan(0);
  });

  it("says zero the moment the microphone is muted", () => {
    vi.useFakeTimers();
    const seen: number[] = [];
    let muted = false;
    const media = host(rising(), (level) => seen.push(level));
    startBargeInGate(media, () => muted);
    vi.advanceTimersByTime(1200);
    expect(seen.at(-1)).toBeGreaterThan(0);
    muted = true;
    vi.advanceTimersByTime(100);
    stopBargeInGate(media);
    vi.useRealTimers();
    // Left unpublished, the body would hold whatever it last heard and go on
    // attending to a person who has switched their microphone off.
    expect(seen.at(-1)).toBe(0);
  });

  it("falls silent the moment SHE starts talking, whatever the mic hears", () => {
    vi.useFakeTimers();
    const seen: number[] = [];
    const media = host(rising(), (level) => seen.push(level));
    startBargeInGate(media, () => false);
    vi.advanceTimersByTime(1200);
    expect(seen.at(-1)).toBeGreaterThan(0);
    // A playing source means the capture is carrying AEC residual rather than a
    // person; a level read off that would have her answering her own voice
    // through the listening channel as well as the speaking one.
    media.playbackSources.add({} as AudioBufferSourceNode);
    vi.advanceTimersByTime(100);
    stopBargeInGate(media);
    vi.useRealTimers();
    expect(seen.at(-1)).toBe(0);
  });
});
