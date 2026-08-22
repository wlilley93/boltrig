// What a voice does to the Familiar, measured rather than eyeballed.
//
// Every assertion here corresponds to a defect the drive used to have. The
// envelope's asymmetry, the silence gate and the beat's decay are all fixes for
// the same complaint from opposite directions -- "her pulsing is too jagged
// when she speaks" -- and each of them is undone by an innocent-looking
// simplification, so each is pinned.

import { describe, expect, it } from "vitest";

import {
  BeatImpulse,
  VoiceEnvelope,
  dayWarmth,
  familiarDrive,
} from "../src/components/familiar/familiarDrive";
import { FAMILIAR_TUNING, type FamiliarTuning } from "../src/components/canvas/familiarTuning";
import { familiarModeTuning } from "../src/components/canvas/familiarPresets";
import { RESTING_STAGE_STATE } from "../src/components/familiar/FamiliarState";
import { FamiliarMood, RESTING_MOOD } from "../src/components/familiar/familiarMood";

const DT = 1 / 30;
const LOUD = [0.9, 0.9, 0.8, 0.8, 0.7, 0.6, 0.5, 0.4];
const smoothers = () => ({ env: new VoiceEnvelope(), beat: new BeatImpulse() });

/** Settle the drive over `frames` identical frames, as a real voice would. */
function settle(
  state: Parameters<typeof familiarDrive>[0],
  tuning: FamiliarTuning,
  frames: number,
) {
  const bag = smoothers();
  let out = familiarDrive(state, bag, DT, 0, tuning);
  for (let i = 1; i < frames; i += 1) {
    out = familiarDrive(state, bag, DT, i * DT, tuning);
  }
  return out;
}

describe("VoiceEnvelope", () => {
  it("rises faster than it falls, which is the whole point of it", () => {
    const [attack, release] = FAMILIAR_TUNING.voiceEnv;
    const up = new VoiceEnvelope();
    up.step("c", 0, DT, attack, release);
    const risen = up.step("c", 1, DT, attack, release);

    const down = new VoiceEnvelope();
    down.step("c", 1, DT, attack, release);
    const fallen = 1 - down.step("c", 0, DT, attack, release);

    // A symmetric envelope slow enough to be calm also arrives late, and a body
    // moving after its own voice is worse than one moving too much.
    expect(risen).toBeGreaterThan(fallen * 2);
  });

  it("is framerate-independent, so a busy machine does not slow the body", () => {
    const fast = new VoiceEnvelope();
    fast.step("c", 0, 1 / 120, 0.09, 0.4);
    for (let i = 0; i < 12; i += 1) fast.step("c", 1, 1 / 120, 0.09, 0.4);

    const slow = new VoiceEnvelope();
    slow.step("c", 0, 1 / 30, 0.09, 0.4);
    for (let i = 0; i < 3; i += 1) slow.step("c", 1, 1 / 30, 0.09, 0.4);

    // Same wall-clock elapsed (0.1s), so the same place in the curve.
    expect(fast.step("c", 1, 0, 0.09, 0.4)).toBeCloseTo(slow.step("c", 1, 0, 0.09, 0.4), 2);
  });
});

describe("BeatImpulse", () => {
  const [gain, decay] = familiarModeTuning("speaking").beat;

  it("holds a syllable open instead of strobing with the flux", () => {
    const beat = new BeatImpulse();
    const landed = beat.step(0.8, DT, gain, decay);
    // Onset is a per-frame DIFFERENCE: it collapses to zero on the very next
    // frame while the vowel is still going. Passed straight through and
    // multiplied hard in five places inside the shader, that is a strobe.
    const next = beat.step(0, DT, gain, decay);
    expect(landed).toBeGreaterThan(0.8);
    expect(next).toBeGreaterThan(landed * 0.5);
  });

  it("still gets out of the way before the next syllable", () => {
    const beat = new BeatImpulse();
    beat.step(1, DT, gain, decay);
    // ~0.4s later, comfortably inside the gap between two words.
    for (let i = 0; i < 12; i += 1) beat.step(0, DT, gain, decay);
    expect(beat.step(0, DT, gain, decay)).toBeLessThan(0.15);
  });

  it("attacks instantly, because smoothing a beat turns it into a swell", () => {
    const beat = new BeatImpulse();
    expect(beat.step(1, DT, 1, decay)).toBe(1);
  });
});

describe("the silence gate", () => {
  const speaking = familiarModeTuning("speaking");

  it("removes the floor without touching a loud frame", () => {
    const quiet = settle(
      { ...RESTING_STAGE_STATE, mode: "speaking", level: 0.03, bands: LOUD.map(() => 0.03) },
      speaking, 20,
    );
    const loud = settle(
      { ...RESTING_STAGE_STATE, mode: "speaking", level: 0.9, bands: LOUD },
      speaking, 20,
    );
    // Room tone, an AEC residual and the codec's own noise floor all sit a few
    // percent above zero, and answering them is the twitch between words.
    expect(quiet.ax).toBe(0);
    expect(loud.ax).toBeGreaterThan(0.6);
  });

  it("judges the whole frame once rather than each band separately", () => {
    // A quiet frame that happens to be noisiest in one band must not let that
    // band through: gating per band smears the spectrum, so the body answers
    // the shape of the noise floor instead of a voice.
    const lopsided = settle(
      {
        ...RESTING_STAGE_STATE, mode: "speaking", level: 0.02,
        bands: [0.9, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02],
      },
      speaking, 20,
    );
    expect(lopsided.ay).toBe(0);
    expect(lopsided.aw).toBe(0);
  });

  it("is open by default, so the struct alone changed nothing on screen", () => {
    expect(FAMILIAR_TUNING.voiceGate[0]).toBe(0);
  });
});

describe("familiarDrive by mode", () => {
  it("puts consonants on the surface and not into the nucleus", () => {
    const sibilant = settle(
      {
        ...RESTING_STAGE_STATE, mode: "speaking", level: 0.6,
        bands: [0.1, 0.1, 0.2, 0.3, 0.5, 0.9, 0.95, 0.9],
      },
      familiarModeTuning("speaking"), 30,
    );
    // uAudio.w lights the filaments; uAudio.y pressurises the nucleus. A
    // sibilant that inflates the nucleus reads as a shout.
    expect(sibilant.aw).toBeGreaterThan(sibilant.ay * 2);
  });

  it("registers a listener without mouthing their words", () => {
    const heard = settle(
      { ...RESTING_STAGE_STATE, mode: "listening", micLevel: 0.9 },
      familiarModeTuning("listening"), 30,
    );
    const spoken = settle(
      { ...RESTING_STAGE_STATE, mode: "speaking", level: 0.9, bands: LOUD },
      familiarModeTuning("speaking"), 30,
    );
    expect(heard.ax).toBeGreaterThan(0);
    // Wired at speaking gain the microphone makes her mouth your words back,
    // which is uncanny in the bad way; wired at zero she is indistinguishable
    // from idle while you are talking to her, which is what shipped.
    expect(heard.ax).toBeLessThan(spoken.ax * 0.5);
    // What she spends on listening is ATTENTION, not amplitude.
    expect(heard.attend).toBeGreaterThan(0.8);
    expect(heard.beat).toBe(0);
  });

  it("attends to a listener who has gone quiet mid-sentence", () => {
    const pause = settle(
      { ...RESTING_STAGE_STATE, mode: "listening", micLevel: 0 },
      familiarModeTuning("listening"), 30,
    );
    // She is attending because you are THERE. A person drawing breath has not
    // stopped being someone she is talking to.
    expect(pause.attend).toBeGreaterThan(0.4);
    expect(pause.ax).toBeCloseTo(0, 3);
  });

  it("stands still in standby and breathes when there is no voice to follow", () => {
    const idle = settle({ ...RESTING_STAGE_STATE, mode: "standby" }, familiarModeTuning("standby"), 5);
    // Working rate is 0.2 Hz: the crest of the breath sits at half the period,
    // t = 2.5s. settle counts FRAMES at 30fps and its last step is (n-1)·DT,
    // so 76 frames lands exactly on the crest.
    const crest = settle({ ...RESTING_STAGE_STATE, mode: "working" }, familiarModeTuning("working"), 76);
    expect(idle.ax).toBe(0);
    expect(idle.attend).toBe(0);
    expect(crest.ax).toBeGreaterThan(0.15);
  });

  it("breathes as ONE coherent swell toward the viewer, resting between breaths", () => {
    // THE BUG THIS PINS. The old idle ran two sines at unrelated rates around a
    // HIGH resting offset: the voice channel idled at ~0.45 (continuously
    // lighting the surface filaments) and the bass channel continuously excited
    // the interior warp, and the author's verdict was "it looks like it's being
    // zapped ... it should pulse towards the user, not rotate left and right".
    // The pinned properties are the fix: both channels rise IN PHASE from a
    // near-zero rest, the crest stays below the filament-ignition region, and
    // the cycle length is literally 1/rate.
    const tuning = familiarModeTuning("working");
    const at = (t: number) => familiarDrive(
      { ...RESTING_STAGE_STATE, mode: "working" }, smoothers(), DT, t, tuning,
    );
    const rest = at(0);
    expect(rest.ax).toBeLessThan(0.01);
    expect(rest.ay).toBeLessThan(0.01);
    const crest = at(2.5);
    expect(crest.ax).toBeGreaterThan(0.15);
    expect(crest.ax).toBeLessThanOrEqual(0.25);
    expect(crest.ay).toBeGreaterThan(crest.ax);
    // Coherence: the two channels are one waveform at two depths, so their
    // ratio holds across the whole cycle instead of beating.
    for (const t of [0.7, 1.4, 2.1, 3.4]) {
      const drive = at(t);
      expect(drive.ay).toBeCloseTo(drive.ax * (1.6 / 1.2), 5);
    }
    // Period: one full breath returns to rest.
    const nextRest = at(5);
    expect(nextRest.ax).toBeLessThan(0.01);
  });

  it("falls back to a level-scaled oscillator when there is no spectrum", () => {
    // The honest degradation: it moves with the voice's volume and knows
    // nothing about its shape, which is exactly what the host reported.
    const loud = settle(
      { ...RESTING_STAGE_STATE, mode: "speaking", level: 0.9, bands: null },
      familiarModeTuning("speaking"), 3,
    );
    const quiet = settle(
      { ...RESTING_STAGE_STATE, mode: "speaking", level: 0.1, bands: null },
      familiarModeTuning("speaking"), 3,
    );
    expect(loud.ax).toBeGreaterThan(quiet.ax);
    expect(loud.attend).toBe(1);
  });
});

describe("dayWarmth", () => {
  it("reads the floor and span off the dial rather than off two literals", () => {
    const noon = new Date(2026, 7, 11, 15, 0, 0).getTime();
    const real = Date.now;
    Date.now = () => noon;
    try {
      const lit = dayWarmth({ ...FAMILIAR_TUNING, daylight: [0.15, 0.85] });
      const dim = dayWarmth({ ...FAMILIAR_TUNING, daylight: [0.0, 0.2] });
      expect(lit).toBeGreaterThan(dim);
      expect(dim).toBeLessThanOrEqual(0.2);
    } finally {
      Date.now = real;
    }
  });
});

describe("FamiliarMood", () => {
  it("eases toward a fresh server reading and hands back when it goes stale", () => {
    const mood = new FamiliarMood();
    mood.seed(0);
    mood.applyPhenotype({ luminosity: 1, valence: 1 }, 0);
    // 200 frames at 33ms is 6.6s -- inside the ten-second freshness window, and
    // three time constants at the phenotype's tau of 2s.
    for (let i = 1; i <= 200; i += 1) mood.tick(i * 33, FAMILIAR_TUNING);
    expect(mood.cur.luminosity).toBeGreaterThan(0.94);

    // Silence from the relay and the wander resumes: an absent relay must look
    // like a calm creature, never a frozen one.
    mood.applyPhenotype(null, 6600);
    const before = mood.cur.luminosity;
    for (let i = 1; i <= 400; i += 1) mood.tick(6600 + i * 33, FAMILIAR_TUNING);
    expect(mood.cur.luminosity).not.toBe(before);
  });

  it("never writes an overlay back into the wander it is laid over", () => {
    const mood = new FamiliarMood();
    mood.seed(0);
    const shown = mood.withOverlay({ tension: 0.75, luminosity: 0.28 });
    expect(shown.tension).toBe(0.75);
    // Written back, an overlay would be eased toward on the next frame and
    // again on the one after -- a state that compounds until it saturates, and
    // an error tone that could never lift off.
    expect(mood.cur.tension).toBe(RESTING_MOOD.tension);
  });
});
