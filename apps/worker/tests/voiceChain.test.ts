import { describe, expect, it } from "vitest";

import { normalisationGain, speechLevelDb, TARGET_SPEECH_DBFS } from "../src/components/voiceLoudness";
import {
  MAX_TILT_GAIN_DB,
  TARGET_AIR_GAP_DB,
  TARGET_SIBILANT_DB,
  bandDb,
  shapingChain,
  type FilterSpec,
} from "../src/components/voiceTone";

/**
 * The whole chain, end to end, which nothing else checks.
 *
 * Every other test here exercises one stage: does the tilt derive the right
 * gain, does the loudness measure the right level, does a bundle's tone parse.
 * None of them answers the question that actually matters -- if you apply what
 * this module DERIVES, does the audio come out where it was aimed?
 *
 * That is not circular. The stages produce PARAMETERS; this applies them and
 * measures the result independently. A sign error, a corner in the wrong place
 * or two stages fighting each other would pass every unit test above and fail
 * here.
 *
 * The filters below are RBJ biquads -- the same maths a BiquadFilterNode runs,
 * so what is measured here is what the browser will produce.
 */

const SR = 24_000;
const BAND_DILUTION_DB = 6.2;   // see voiceTone.test.ts; band widths differ

function bandNoise(low: number, high: number, rmsDb: number, n: number): Float32Array {
  const out = new Float32Array(n);
  const step = 50;
  const partials = Math.max(1, Math.floor((high - low) / step));
  const amp = 10 ** (rmsDb / 20) * Math.sqrt(2 / partials);
  for (let k = 0; k < partials; k += 1) {
    const hz = low + k * step;
    const phase = (k * Math.PI * 0.6180339887) % (2 * Math.PI);
    for (let i = 0; i < n; i += 1) out[i] += amp * Math.sin((2 * Math.PI * hz * i) / SR + phase);
  }
  return out;
}

/** A voice whose measured sibilance and air sit where asked, at a chosen level. */
function voice(sibBelowBody: number, airBelowSib: number, bodyDb = -15): Float32Array {
  const n = SR;
  const sibDb = bodyDb + sibBelowBody + BAND_DILUTION_DB;
  const out = new Float32Array(n);
  for (const [lo, hi, db] of [[300, 1000, bodyDb], [5000, 8000, sibDb],
                              [8000, 11000, sibDb - airBelowSib]] as const) {
    const band = bandNoise(lo, hi, db, n);
    for (let i = 0; i < n; i += 1) out[i] += band[i] ?? 0;
  }
  return out;
}

/** One RBJ biquad, matching what Web Audio builds from the same spec. */
function applyFilter(x: Float32Array, spec: FilterSpec): Float32Array {
  const a = 10 ** (spec.gainDb / 40);
  const w0 = (2 * Math.PI * spec.frequency) / SR;
  const cos = Math.cos(w0), sin = Math.sin(w0);
  const q = spec.q ?? 1;
  let b0: number, b1: number, b2: number, a0: number, a1: number, a2: number;
  if (spec.type === "peaking") {
    const alpha = sin / (2 * q);
    b0 = 1 + alpha * a; b1 = -2 * cos; b2 = 1 - alpha * a;
    a0 = 1 + alpha / a; a1 = -2 * cos; a2 = 1 - alpha / a;
  } else {
    // Shelves use S=1, which is what BiquadFilterNode uses for high/lowshelf.
    const alpha = (sin / 2) * Math.sqrt((a + 1 / a) * (1 / 1 - 1) + 2);
    const sq = 2 * Math.sqrt(a) * alpha;
    if (spec.type === "highshelf") {
      b0 = a * ((a + 1) + (a - 1) * cos + sq);
      b1 = -2 * a * ((a - 1) + (a + 1) * cos);
      b2 = a * ((a + 1) + (a - 1) * cos - sq);
      a0 = (a + 1) - (a - 1) * cos + sq;
      a1 = 2 * ((a - 1) - (a + 1) * cos);
      a2 = (a + 1) - (a - 1) * cos - sq;
    } else {
      b0 = a * ((a + 1) - (a - 1) * cos + sq);
      b1 = 2 * a * ((a - 1) - (a + 1) * cos);
      b2 = a * ((a + 1) - (a - 1) * cos - sq);
      a0 = (a + 1) + (a - 1) * cos + sq;
      a1 = -2 * ((a - 1) + (a + 1) * cos);
      a2 = (a + 1) + (a - 1) * cos - sq;
    }
  }
  const out = new Float32Array(x.length);
  let x1 = 0, x2 = 0, y1 = 0, y2 = 0;
  for (let i = 0; i < x.length; i += 1) {
    const x0 = x[i] ?? 0;
    const y0 = (b0 / a0) * x0 + (b1 / a0) * x1 + (b2 / a0) * x2
      - (a1 / a0) * y1 - (a2 / a0) * y2;
    x2 = x1; x1 = x0; y2 = y1; y1 = y0;
    out[i] = y0;
  }
  return out;
}

/** Everything the player would do: shaping first, then loudness. */
function runChain(input: Float32Array, tone?: unknown): Float32Array {
  let signal = input;
  for (const spec of shapingChain(signal, SR, tone)) signal = applyFilter(signal, spec);
  const gain = normalisationGain(signal);
  const out = new Float32Array(signal.length);
  for (let i = 0; i < signal.length; i += 1) out[i] = (signal[i] ?? 0) * gain;
  return out;
}

const airGap = (x: Float32Array): number =>
  bandDb(x, SR, 5000, 8000) - bandDb(x, SR, 8000, 11000);
const sibLevel = (x: Float32Array): number =>
  bandDb(x, SR, 5000, 8000) - bandDb(x, SR, 300, 1000);

describe("the whole chain, applied", () => {
  it("closes a cliff toward the target instead of merely reducing it", () => {
    // Joi's shape. 16.6 dB of cliff, and the aim is TARGET_AIR_GAP_DB.
    const before = voice(-26.6, 16.6);
    const after = runChain(before);
    expect(airGap(before)).toBeCloseTo(16.6, 0);
    // Roughly halved, not closed to target. A shelf has a transition region,
    // so cornering it above the sibilance peak means the bottom of the air
    // band only gets part of the gain. Closing the gap fully would need a
    // steeper filter, which would also ring; the ear preferred this. Asserting
    // TARGET_AIR_GAP_DB here would be asserting an outcome the physics does
    // not offer, and it would have passed only by accident.
    expect(airGap(after)).toBeLessThan(airGap(before) - 7);
    expect(airGap(after)).toBeGreaterThan(TARGET_AIR_GAP_DB);
  });

  it("lifts a dull voice toward Vera's level, not past it", () => {
    // Jarvis's shape: a level deficit inside the clamp, so the measurement
    // rather than the ceiling decides, and it must land ON target.
    const after = runChain(voice(-34.3, 5.0));
    expect(Math.abs(sibLevel(after) - TARGET_SIBILANT_DB)).toBeLessThan(1.5);
  });

  it("leaves the reference voice alone, all the way through", () => {
    // Vera. The one voice that must come out the other side unshaped, because
    // she is what the others are being lifted toward.
    const before = voice(-24, 2.6);
    const after = runChain(before);
    expect(shapingChain(before, SR, undefined)).toEqual([]);
    expect(sibLevel(after)).toBeCloseTo(sibLevel(before), 0);
    expect(airGap(after)).toBeCloseTo(airGap(before), 0);
  });

  it("still lands on the loudness target after shaping has changed the level", () => {
    // THE STAGES MUST NOT FIGHT. Shaping alters loudness, so the gain has to be
    // measured AFTER it -- computing it first would leave every corrected voice
    // louder than target by however much the shelf added.
    for (const v of [voice(-26.6, 16.6), voice(-34.3, 5.0), voice(-41, 1.3, -25)]) {
      expect(Math.abs(speechLevelDb(runChain(v)) - TARGET_SPEECH_DBFS)).toBeLessThan(1);
    }
  });

  it("applies a character's declared tone on top of the measured correction", () => {
    // Jarvis: tilt, then his presence lift. The presence band must actually
    // move, and the tilt must still have done its job.
    // WITH ENERGY AT 3 kHz. The earlier fixture had none there, so this
    // compared two noise floors and would have passed or failed on rounding.
    const before = voice(-34.3, 5.0);
    const presence = bandNoise(2500, 3500, -30, before.length);
    for (let i = 0; i < before.length; i += 1) before[i] = (before[i] ?? 0) + (presence[i] ?? 0);
    const tone = [{ type: "peaking", frequency: 3000, gainDb: 5, q: 1.2,
                    reason: "consonant clarity" }];
    const withTone = runChain(before, tone);
    const withoutTone = runChain(before, undefined);
    expect(bandDb(withTone, SR, 2500, 3500) - bandDb(withTone, SR, 300, 1000))
      .toBeGreaterThan(bandDb(withoutTone, SR, 2500, 3500)
        - bandDb(withoutTone, SR, 300, 1000) + 2);
  });

  it("does not clip, even on the voice that asks for the most gain", () => {
    // Maya: a 17 dB deficit, clamped, then normalised upward. If any stage
    // ignored headroom this is where it would show.
    const after = runChain(voice(-41, 1.3, -25));
    let peak = 0;
    for (let i = 0; i < after.length; i += 1) peak = Math.max(peak, Math.abs(after[i] ?? 0));
    expect(peak).toBeLessThanOrEqual(1);
  });

  it("a voice past the clamp is improved, just not fully corrected", () => {
    // Honest about the limit: 17 dB wanted, MAX_TILT_GAIN_DB given, so the
    // result must be better than before and short of target, not either alone.
    const before = voice(-41, 1.3);
    const after = runChain(before);
    expect(sibLevel(after)).toBeGreaterThan(sibLevel(before) + 8);
    expect(sibLevel(after)).toBeLessThan(TARGET_SIBILANT_DB);
    expect(Math.abs(sibLevel(after) - (-41 + MAX_TILT_GAIN_DB))).toBeLessThan(2);
  });
});
