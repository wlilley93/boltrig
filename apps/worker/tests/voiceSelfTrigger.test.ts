import { afterEach, describe, expect, it, vi } from "vitest";

import {
  BARGE_IN_FRAME_MS,
  BARGE_IN_TRIGGER_FRAMES,
  createBargeInGate,
} from "../src/components/voiceBargeIn";
import {
  BARGE_IN_DIAGNOSTIC_EVENT,
  bargeInHostFields,
  startBargeInGate,
  stopBargeInGate,
  type BargeInFrameDiagnostic,
  type BargeInHost,
} from "../src/components/voiceBargeInGraph";
import {
  BARGE_IN_SELF_TRIGGER_DEFAULTS,
  createSelfTriggerGuard,
  resolveSelfTriggerTuning,
  type BargeInSelfTriggerMode,
  type SelfTriggerTuning,
} from "../src/components/voiceSelfTrigger";

// The measured room, from docs/BARGEIN-2026-08-13.md.
const ROOM_FLOOR = 0.000_9; // ~ -61 dBFS, the inter-word floor of real captures
const USER_SPEECH = 0.05; // ~ -26 dBFS, median voiced level of real captures
const HER_PLAYBACK = 0.1; // ~ -20 dBFS on the playback bus during a syllable
const HER_SILENCE = 0.000_5; // between her words, on the bus
const COUPLING = 0.1; // -20dB bus-to-microphone: 0.01 = -40 dBFS residual

/** Uncorrelated signals add in power, not amplitude. */
function mix(...levels: number[]): number {
  return Math.sqrt(levels.reduce((total, level) => total + level * level, 0));
}

/**
 * Her turn as the microphone and the playback bus each see it: syllables of
 * `syllableFrames` separated by gaps of `gapFrames`. Speech-shaped, because a
 * *stationary* residual at the same RMS never triggered the gate (0/4 at
 * -30 dBFS) and this modulation did (6/6 at -40 dBFS).
 */
function herTurn(
  frames: number,
  { syllableFrames = 12, gapFrames = 12 } = {},
): number[] {
  const period = syllableFrames + gapFrames;
  return Array.from({ length: frames }, (_unused, index) => (
    index % period < syllableFrames ? HER_PLAYBACK : HER_SILENCE
  ));
}

interface Run {
  triggers: number[];
  frames: number;
}

/**
 * Warm the room floor, start a turn, and play `bus` out while the microphone
 * hears its residual plus whatever `userFrom` adds.
 */
function playTurn(
  mode: BargeInSelfTriggerMode,
  bus: number[],
  { userFrom = Number.POSITIVE_INFINITY, tuning = {} as Partial<SelfTriggerTuning> } = {},
): Run {
  const gate = createBargeInGate({
    selfTrigger: createSelfTriggerGuard({
      ...BARGE_IN_SELF_TRIGGER_DEFAULTS,
      ...tuning,
      mode,
    }),
  });
  for (let index = 0; index < 80; index += 1) {
    gate.observe({ rms: ROOM_FLOOR, playing: false, now: index * BARGE_IN_FRAME_MS, reference: 0 });
  }
  const triggers: number[] = [];
  for (let index = 0; index < bus.length; index += 1) {
    const reference = bus[index] ?? 0;
    const user = index >= userFrom ? USER_SPEECH : 0;
    const verdict = gate.observe({
      rms: mix(reference * COUPLING, ROOM_FLOOR, user),
      playing: true,
      now: 800 + index * BARGE_IN_FRAME_MS,
      reference,
    });
    if (verdict.trigger) triggers.push(index);
  }
  return { triggers, frames: bus.length };
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

interface FakeAnalyser {
  fftSize: number;
  level: number;
  getFloatTimeDomainData(frame: Float32Array): void;
}

function fakeAnalyser(level: number): FakeAnalyser {
  const analyser: FakeAnalyser = {
    fftSize: 512,
    level,
    getFloatTimeDomainData(frame) {
      frame.fill(analyser.level);
    },
  };
  return analyser;
}

/** A `window` with just the three members the poll touches. */
function stubWindow(): BargeInFrameDiagnostic[] {
  const frames: BargeInFrameDiagnostic[] = [];
  vi.stubGlobal("window", {
    setInterval: (handler: () => void, ms: number) => globalThis.setInterval(handler, ms),
    clearInterval: (id: number) => globalThis.clearInterval(id),
    dispatchEvent: (event: CustomEvent<BargeInFrameDiagnostic>) => {
      frames.push(event.detail);
      return true;
    },
  });
  return frames;
}

/** Drive the real ~10ms poll through one of her turns and report what it saw. */
function pollTurn(mode: BargeInSelfTriggerMode): {
  interrupts: number;
  diagnostics: BargeInFrameDiagnostic[];
} {
  const diagnostics = stubWindow();
  vi.useFakeTimers();
  const mic = fakeAnalyser(ROOM_FLOOR);
  const bus = fakeAnalyser(0);
  const fired = vi.fn();
  const host: BargeInHost = {
    playbackSources: new Set<AudioBufferSourceNode>(),
    analyser: bus as unknown as AnalyserNode,
    ...bargeInHostFields(mic as unknown as AnalyserNode, fired, {
      ...BARGE_IN_SELF_TRIGGER_DEFAULTS,
      mode,
    }),
  };
  startBargeInGate(host, () => false);
  vi.advanceTimersByTime(80 * BARGE_IN_FRAME_MS); // warm the room floor
  host.playbackSources.add({} as AudioBufferSourceNode);
  for (let syllable = 0; syllable < 10; syllable += 1) {
    mic.level = HER_PLAYBACK * COUPLING;
    bus.level = HER_PLAYBACK;
    vi.advanceTimersByTime(12 * BARGE_IN_FRAME_MS);
    mic.level = ROOM_FLOOR;
    bus.level = HER_SILENCE;
    vi.advanceTimersByTime(12 * BARGE_IN_FRAME_MS);
  }
  stopBargeInGate(host);
  return { interrupts: fired.mock.calls.length, diagnostics };
}

describe("the reference reaches the gate through the real poll", () => {
  it("self-triggers unmitigated and stops once a mitigation is switched on", () => {
    // Same signal three times, through `startBargeInGate` rather than the pure
    // gate: proof that the playback analyser is wired as the reference and not
    // merely available.
    expect(pollTurn("echo-floor").interrupts).toBeGreaterThan(0);
    expect(pollTurn("reference-margin").interrupts).toBe(0);
    expect(pollTurn("playback-hangover").interrupts).toBe(0);
  });

  it("says nothing at all unless diagnostics are asked for", () => {
    expect(pollTurn("reference-margin").diagnostics).toEqual([]);
  });

  it("publishes both levels per frame when they are, which is the measurement", () => {
    vi.stubEnv("VITE_BARGE_IN_DIAGNOSTICS", "1");
    const { diagnostics } = pollTurn("reference-margin");
    const speaking = diagnostics.filter((frame) => frame.playing && frame.reference > HER_SILENCE);
    expect(speaking.length).toBeGreaterThan(50);
    // Echo coupling, the number the operator has to measure in their own room:
    // microphone dBFS minus playback-bus dBFS while she speaks and they do not.
    const coupling = 20 * Math.log10((speaking[0]?.rms ?? 0) / (speaking[0]?.reference ?? 1));
    expect(coupling).toBeCloseTo(20 * Math.log10(COUPLING), 1);
  });
});

describe("the open defect", () => {
  it("reproduces: echo-floor mode interrupts her on her own speech-shaped residual", () => {
    // -40 dBFS of residual, the level that self-triggered 6/6 in the real
    // measurement. This test exists to fail loudly if a later change claims to
    // have fixed the defect without switching modes.
    const run = playTurn("echo-floor", herTurn(200));
    expect(run.triggers.length).toBeGreaterThan(0);
    expect(run.triggers[0]).toBeLessThan(100); // within the first second
  });

  it("is not a threshold that is slightly off: a stationary residual never fired", () => {
    // Same RMS, no modulation. Confirms the diagnosis the mitigations rest on.
    const run = playTurn("echo-floor", Array.from({ length: 200 }, () => HER_PLAYBACK));
    expect(run.triggers).toEqual([]);
  });
});

describe("reference-margin mitigation", () => {
  it("keeps her own leakage under the bar for a whole turn", () => {
    expect(playTurn("reference-margin", herTurn(400)).triggers).toEqual([]);
  });

  it("survives a residual far louder than the one that breaks echo-floor", () => {
    // -14 dBFS bus-to-microphone coupling would leave -34 dBFS in the mic. The
    // bar is relative, so a louder residual raises it by exactly as much.
    const run = playTurn("reference-margin", herTurn(400), {
      tuning: { couplingDb: -6 },
    });
    expect(run.triggers).toEqual([]);
  });

  it("still hears the user over her, with the trigger window unchanged", () => {
    const onset = 100;
    const run = playTurn("reference-margin", herTurn(200), { userFrom: onset });
    expect(run.triggers[0]).toBe(onset + BARGE_IN_TRIGGER_FRAMES - 1);
  });

  it("does not let the bar sink into the gaps between her words", () => {
    // The failure mode of the floor tracker, restated as a property: the bar
    // must fall slower than her own modulation.
    const guard = createSelfTriggerGuard(BARGE_IN_SELF_TRIGGER_DEFAULTS);
    const observe = (reference: number) =>
      guard.observe({ reference, playing: true, frameMs: BARGE_IN_FRAME_MS });
    for (let index = 0; index < 12; index += 1) observe(HER_PLAYBACK);
    let envelope = 0;
    for (let index = 0; index < 20; index += 1) envelope = observe(HER_SILENCE).envelope;
    // 24dB/s across 200ms of silence is 4.8dB, and the residual it has to cover
    // vanished with the syllable that caused it.
    expect(20 * Math.log10(envelope / HER_PLAYBACK)).toBeGreaterThan(-6);
  });
});

describe("playback-hangover mitigation", () => {
  it("cannot fire while her audio is audible, however modulated", () => {
    expect(playTurn("playback-hangover", herTurn(400)).triggers).toEqual([]);
  });

  it("is immune at a residual that no relative bar was tuned for", () => {
    const run = playTurn("playback-hangover", herTurn(400), {
      tuning: { couplingDb: 0 },
    });
    expect(run.triggers).toEqual([]);
  });

  it("hears the user only in a gap longer than the hangover, and that is its cost", () => {
    const onset = 100; // mid-syllable
    const run = playTurn("playback-hangover", herTurn(200), {
      userFrom: onset,
      tuning: { hangoverMs: 40 },
    });
    const fired = run.triggers[0];
    expect(fired).toBeDefined();
    // reference-margin fires on frame onset+2. This waits out the rest of her
    // syllable plus the hangover: tens of milliseconds of extra latency, which
    // is the whole trade and is why it is not the default.
    expect(fired!).toBeGreaterThan(onset + BARGE_IN_TRIGGER_FRAMES);
  });

  it("never fires at all when every gap is shorter than the hangover", () => {
    // The honest limit: the gate needs `hangoverMs` plus three frames of clear
    // air, so with the default 80ms hangover and 60ms gaps the user cannot get
    // in at all until she pauses. Tune `hangoverMs` against real speech.
    const run = playTurn("playback-hangover", herTurn(200, { gapFrames: 6 }), {
      userFrom: 100,
    });
    expect(run.triggers).toEqual([]);
  });
});

describe("the switch", () => {
  it("defaults to neither mitigation", () => {
    expect(resolveSelfTriggerTuning()).toEqual(BARGE_IN_SELF_TRIGGER_DEFAULTS);
    expect(BARGE_IN_SELF_TRIGGER_DEFAULTS.mode).toBe("echo-floor");
  });

  it("reads the build-time environment", () => {
    vi.stubEnv("VITE_BARGE_IN_SELF_TRIGGER_MODE", "reference-margin");
    vi.stubEnv("VITE_BARGE_IN_ECHO_COUPLING_DB", "-27.5");
    const tuning = resolveSelfTriggerTuning();
    expect(tuning.mode).toBe("reference-margin");
    expect(tuning.couplingDb).toBe(-27.5);
  });

  it("lets localStorage win, so the room can be measured without a rebuild", () => {
    vi.stubEnv("VITE_BARGE_IN_SELF_TRIGGER_MODE", "reference-margin");
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => (key === "boltrig.bargeIn.mode" ? "playback-hangover" : null),
    });
    expect(resolveSelfTriggerTuning().mode).toBe("playback-hangover");
  });

  it("ignores a value it does not recognise rather than guessing", () => {
    vi.stubEnv("VITE_BARGE_IN_SELF_TRIGGER_MODE", "aggressive");
    vi.stubEnv("VITE_BARGE_IN_HANGOVER_MS", "soon");
    const tuning = resolveSelfTriggerTuning();
    expect(tuning.mode).toBe("echo-floor");
    expect(tuning.hangoverMs).toBe(BARGE_IN_SELF_TRIGGER_DEFAULTS.hangoverMs);
  });

  it("survives a webview that refuses storage", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("storage disabled");
      },
    });
    expect(() => resolveSelfTriggerTuning()).not.toThrow();
  });
});
