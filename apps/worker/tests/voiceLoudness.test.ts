import { describe, expect, it } from "vitest";

import {
  MAX_GAIN_DB,
  PEAK_CEILING_DBFS,
  TARGET_SPEECH_DBFS,
  UtteranceGain,
  normalisationGain,
  pcm16ToFloat,
  peakDb,
  speechLevelDb,
} from "../src/components/voiceLoudness";

const SR = 24_000;

/** A sine at a known RMS, so the measurement has a right answer to hit. */
function tone(rms: number, seconds = 1, hz = 200): Float32Array {
  const n = Math.floor(SR * seconds);
  const amplitude = rms * Math.SQRT2; // RMS of a sine is A/sqrt2
  const out = new Float32Array(n);
  for (let i = 0; i < n; i += 1) out[i] = amplitude * Math.sin((2 * Math.PI * hz * i) / SR);
  return out;
}

const dbToAmp = (db: number): number => 10 ** (db / 20);
const ampToDb = (a: number): number => 20 * Math.log10(a);

/** Speech level of `samples` after `gain`, which is what the listener hears. */
const levelAfter = (samples: Float32Array, gain: number): number =>
  speechLevelDb(samples.map((s) => s * gain) as Float32Array);

describe("speechLevelDb", () => {
  it("measures a known tone to within a fraction of a dB", () => {
    expect(speechLevelDb(tone(dbToAmp(-20)))).toBeCloseTo(-20, 0);
    expect(speechLevelDb(tone(dbToAmp(-30)))).toBeCloseTo(-30, 0);
  });

  it("ignores trailing silence, which whole-buffer RMS would not", () => {
    // THE REASON THIS FUNCTION IS NOT A PLAIN RMS. The same speech with a long
    // tail must not read as quieter, or every line that ends with a pause gets
    // boosted for having ended with a pause.
    const speech = tone(dbToAmp(-20), 1);
    const padded = new Float32Array(SR * 3);
    padded.set(speech, 0);
    expect(speechLevelDb(padded)).toBeCloseTo(speechLevelDb(speech), 0);

    const plainRms = (s: Float32Array): number => {
      let sum = 0;
      for (const v of s) sum += v * v;
      return ampToDb(Math.sqrt(sum / s.length));
    };
    // The naive measure is fooled by ~5 dB on the same audio.
    expect(plainRms(speech) - plainRms(padded)).toBeGreaterThan(4);
  });

  it("reports silence as -Infinity and survives an empty buffer", () => {
    expect(speechLevelDb(new Float32Array(SR))).toBe(Number.NEGATIVE_INFINITY);
    expect(speechLevelDb(new Float32Array(0))).toBe(Number.NEGATIVE_INFINITY);
  });

  it("measures a buffer shorter than one frame rather than calling it silent", () => {
    expect(speechLevelDb(tone(dbToAmp(-20), 0.01))).toBeCloseTo(-20, 0);
  });
});

describe("normalisationGain", () => {
  it("brings quiet and loud utterances to the same level", () => {
    // Within the clamp: -26 needs +10 dB and -12 needs -4, both reachable.
    const quiet = tone(dbToAmp(-26));
    const loud = tone(dbToAmp(-12));
    const after = [quiet, loud].map((s) => levelAfter(s, normalisationGain(s)));
    expect(after[0]).toBeCloseTo(TARGET_SPEECH_DBFS, 0);
    expect(after[1]).toBeCloseTo(TARGET_SPEECH_DBFS, 0);
    expect(Math.abs((after[0] ?? 0) - (after[1] ?? 0))).toBeLessThan(0.5);
  });

  it("stops short of the target rather than boosting past the clamp", () => {
    // Documents the limit instead of hiding it. -30 dBFS speech would need
    // +14 dB to reach target and only gets MAX_GAIN_DB, because boosting that
    // hard lifts the noise floor with it. Quieter than intended is the
    // deliberate outcome, and it must stay visible.
    const veryQuiet = tone(dbToAmp(-30));
    const gain = normalisationGain(veryQuiet);
    expect(ampToDb(gain)).toBeCloseTo(MAX_GAIN_DB, 1);
    expect(levelAfter(veryQuiet, gain)).toBeLessThan(TARGET_SPEECH_DBFS - 1);
  });

  it("closes the 3.2 dB spread measured across Maya's registers", () => {
    // The actual numbers from 2026-08-15: quietest register -16.6, loudest
    // -13.4. This is the defect the module exists for.
    const levels = [-16.6, -15.9, -15.7, -15.6, -15.1, -14.6, -14.5, -13.4];
    const after = levels.map((db) => {
      const s = tone(dbToAmp(db));
      return levelAfter(s, normalisationGain(s));
    });
    const spread = Math.max(...after) - Math.min(...after);
    expect(spread).toBeLessThan(0.5);
  });

  it("never lets the result clip, even when the target asks for more", () => {
    // A quiet average with a loud transient: the average wants gain, the peak
    // cannot take it. The peak guard must win.
    const s = tone(dbToAmp(-40), 1);
    s[100] = 0.95;
    // Hoisted out of the map: it was recomputing the gain over the whole
    // buffer once PER SAMPLE, which is the same answer (map does not mutate s)
    // at 48000x the cost -- it fitted in the 5s timeout on an idle machine and
    // timed out on a loaded one, which read as a flaky assertion.
    const gain = normalisationGain(s);
    const out = s.map((v) => v * gain) as Float32Array;
    expect(peakDb(out)).toBeLessThanOrEqual(PEAK_CEILING_DBFS + 0.01);
  });

  it("clamps rather than amplifying near-silence into noise", () => {
    const nearSilent = tone(dbToAmp(-90));
    expect(ampToDb(normalisationGain(nearSilent))).toBeLessThanOrEqual(MAX_GAIN_DB + 0.01);
  });

  it("leaves unmeasurable audio completely untouched", () => {
    expect(normalisationGain(new Float32Array(SR))).toBe(1);
    expect(normalisationGain(new Float32Array(0))).toBe(1);
  });
});

describe("UtteranceGain", () => {
  it("holds one gain across chunks so loudness cannot pump mid-sentence", () => {
    // THE ARTEFACT THIS PREVENTS. Chunks of one utterance legitimately differ
    // in level; normalising each independently would flatten that variation
    // into a wobble, which sounds worse than the inconsistency being fixed.
    const held = new UtteranceGain();
    const first = held.forChunk(tone(dbToAmp(-20), 0.1));
    const onQuieter = held.forChunk(tone(dbToAmp(-32), 0.1));
    const onLouder = held.forChunk(tone(dbToAmp(-11), 0.1));
    expect(onQuieter).toBe(first);
    expect(onLouder).toBe(first);
  });

  it("does not let a silent lead-in decide the utterance's gain", () => {
    const held = new UtteranceGain();
    expect(held.forChunk(new Float32Array(2048))).toBe(1);
    expect(held.decided).toBe(false);
    const real = held.forChunk(tone(dbToAmp(-30), 0.1));
    expect(held.decided).toBe(true);
    expect(real).not.toBe(1);
  });

  it("re-decides after reset, which is the utterance boundary", () => {
    const held = new UtteranceGain();
    const quiet = held.forChunk(tone(dbToAmp(-30), 0.1));
    held.reset();
    const loud = held.forChunk(tone(dbToAmp(-12), 0.1));
    expect(loud).toBeLessThan(quiet);
  });
});

describe("pcm16ToFloat", () => {
  it("round-trips the full-scale endpoints", () => {
    const out = pcm16ToFloat(Int16Array.from([0, 16_384, -32_768]));
    expect(out[0]).toBe(0);
    expect(out[1]).toBeCloseTo(0.5, 5);
    expect(out[2]).toBe(-1);
  });
});
