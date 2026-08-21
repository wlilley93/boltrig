import { describe, expect, it } from "vitest";

import {
  MAX_TILT_GAIN_DB,
  MAX_TONE_GAIN_DB,
  TARGET_AIR_GAP_DB,
  bandDb,
  shapingChain,
  sibilancePeakHz,
  tiltCorrection,
  toneFilters,
} from "../src/components/voiceTone";

const SR = 24_000;

/**
 * Band-limited noise, at a level chosen so the MEASUREMENT lands where stated.
 *
 * Two calibration facts, both established by measuring rather than assuming,
 * and both of which broke earlier versions of this file:
 *
 *   1. Single tones will not do. `bandDb` averages over every FFT bin in a
 *      band, so one tone in the 3 kHz-wide sibilant band is diluted across
 *      ~256 bins while a tone in the 700 Hz-wide body band is diluted across
 *      ~60. The fixture then reports band levels nothing like the ones it was
 *      written to express.
 *   2. Even filling the bands, the two are diluted differently, by a constant
 *      6.2 dB. `bandDb` returns un-normalised magnitudes -- only DIFFERENCES
 *      are meaningful, which is all tiltCorrection uses -- so the fixture
 *      compensates rather than pretending the absolute numbers mean anything.
 *
 * `sibBelowBody` and `airBelowSib` are therefore what the code will MEASURE,
 * which is what the real-voice figures in voiceTone.ts are quoted in.
 */
const BAND_DILUTION_DB = 6.2;

function bandNoise(low: number, high: number, rmsDb: number, n: number): Float32Array {
  const out = new Float32Array(n);
  const step = 50;
  const partials = Math.max(1, Math.floor((high - low) / step));
  const amp = 10 ** (rmsDb / 20) * Math.sqrt(2 / partials);
  for (let k = 0; k < partials; k += 1) {
    const hz = low + k * step;
    // Deterministic per-partial phase: stable across runs, but not all zero,
    // which would sum into one enormous transient at t=0.
    const phase = (k * Math.PI * 0.6180339887) % (2 * Math.PI);
    for (let i = 0; i < n; i += 1) {
      out[i] += amp * Math.sin((2 * Math.PI * hz * i) / SR + phase);
    }
  }
  return out;
}

/** A voice whose MEASURED sibilance and air sit where asked. */
function voice(sibBelowBody: number, airBelowSib: number, seconds = 1): Float32Array {
  const n = Math.floor(SR * seconds);
  const bodyDb = -15;
  const sibDb = bodyDb + sibBelowBody + BAND_DILUTION_DB;
  const airDb = sibDb - airBelowSib;
  const out = new Float32Array(n);
  for (const [lo, hi, db] of [[300, 1000, bodyDb], [5000, 8000, sibDb],
                              [8000, 11000, airDb]] as const) {
    const band = bandNoise(lo, hi, db, n);
    for (let i = 0; i < n; i += 1) out[i] += band[i] ?? 0;
  }
  return out;
}

/** A single tone, for the band-selectivity tests where one is what is meant. */
function tone(hz: number, db: number, seconds = 1): Float32Array {
  const n = Math.floor(SR * seconds);
  const out = new Float32Array(n);
  const amp = 10 ** (db / 20) * Math.SQRT2;
  for (let i = 0; i < n; i += 1) out[i] = amp * Math.sin((2 * Math.PI * hz * i) / SR);
  return out;
}

describe("the fixtures themselves", () => {
  it("measures where it says it does", () => {
    // Guards BAND_DILUTION_DB. If the band edges or the transform change, this
    // fails loudly instead of every tilt test silently testing a spectrum that
    // is not the one it names.
    const v = voice(-26.6, 16.6);
    const body = bandDb(v, SR, 300, 1000);
    const sib = bandDb(v, SR, 5000, 8000);
    const air = bandDb(v, SR, 8000, 11000);
    expect(sib - body).toBeCloseTo(-26.6, 0);
    expect(sib - air).toBeCloseTo(16.6, 0);
  });
});

describe("bandDb", () => {
  it("finds a tone in its own band and not in another", () => {
    const s = tone(600, -20);
    expect(bandDb(s, SR, 300, 1000)).toBeGreaterThan(-26);
    expect(bandDb(s, SR, 5000, 8000)).toBeLessThan(-55);
  });

  it("is monotonic in level", () => {
    const loud = bandDb(tone(600, -12), SR, 300, 1000);
    const quiet = bandDb(tone(600, -30), SR, 300, 1000);
    expect(loud - quiet).toBeCloseTo(18, 0);
  });

  it("returns -Infinity for silence rather than a floor value", () => {
    expect(bandDb(new Float32Array(SR), SR, 300, 1000)).toBe(Number.NEGATIVE_INFINITY);
    expect(bandDb(new Float32Array(0), SR, 300, 1000)).toBe(Number.NEGATIVE_INFINITY);
  });
});

describe("sibilancePeakHz", () => {
  it("locates the peak where the energy actually is", () => {
    expect(sibilancePeakHz(tone(6000, -20), SR)).toBeCloseTo(6000, -2);
    expect(sibilancePeakHz(tone(9000, -20), SR)).toBeCloseTo(9000, -2);
  });

  it("never returns a band the sample rate cannot represent", () => {
    // At 16 kHz, Nyquist is 8 kHz. Bands above it would otherwise "win" by
    // measuring the filter's own ringing rather than any signal.
    const peak = sibilancePeakHz(tone(6000, -20), 16_000);
    expect(peak).toBeLessThan(8_000);
  });
});

describe("tiltCorrection", () => {
  it("does nothing to a voice that is already bright and even", () => {
    // Vera's shape: sibilance near target and a small gap. Nothing to fix.
    expect(tiltCorrection(voice(-24, 2.6), SR)).toBeNull();
  });

  it("corrects a DULL voice whose spectrum has no cliff at all", () => {
    // THE CASE THE FIRST VERSION MISSED. Maya's gap is 1.3 dB -- her shape is
    // fine -- but her whole top end sits seventeen dB under Vera's. Measuring
    // the cliff alone derived nothing for her, contradicting a listening pass
    // that had just called her improved by a shelf.
    const dull = voice(-41, 1.3);
    const spec = tiltCorrection(dull, SR);
    expect(spec).not.toBeNull();
    expect(spec!.gainDb).toBeGreaterThan(5);
    expect(spec!.reason).toMatch(/top end/);
  });

  it("takes whichever deficit asks for more", () => {
    // A cliff voice reports the cliff; a dull voice reports the level.
    expect(tiltCorrection(voice(-26.6, 16.6), SR)!.reason).toMatch(/air .* below sibilance/);
    expect(tiltCorrection(voice(-41, 1.3), SR)!.reason).toMatch(/top end/);
  });

  it("corrects a cliff, and by about the measured deficit", () => {
    // joi's shape: sibilance present, air 16 dB below it.
    const spec = tiltCorrection(voice(-26.6, 16.6), SR);
    expect(spec).not.toBeNull();
    expect(spec!.type).toBe("highshelf");
    expect(spec!.gainDb).toBeGreaterThan(8);
    expect(spec!.gainDb).toBeLessThanOrEqual(MAX_TILT_GAIN_DB);
  });

  it("puts the corner ABOVE the sibilance peak, never on it", () => {
    // THE BUG THIS PREVENTS. Vera's sibilance peaks at 6 kHz; a shelf cornered
    // there boosts her "sss" instead of the air above it, which is audible as
    // harshness rather than as presence.
    const spec = tiltCorrection(voice(-26.6, 16.6), SR);
    expect(spec).not.toBeNull();
    expect(spec!.frequency).toBeGreaterThan(6000);
  });

  it("never boosts, only ever lifts toward the target", () => {
    // An air-rich voice must not be attenuated into the target from above.
    const spec = tiltCorrection(voice(-24, -18), SR);
    expect(spec).toBeNull();
  });

  it("leaves the target gap rather than flattening the spectrum", () => {
    // A gap inside the clamp, so the arithmetic is what is under test.
    const s = voice(-24, 9);
    const spec = tiltCorrection(s, SR)!;
    const gapBefore = bandDb(s, SR, 5000, 8000) - bandDb(s, SR, 8000, 11000);
    expect(spec.gainDb).toBeLessThan(gapBefore);
    expect(spec.gainDb).toBeCloseTo(gapBefore - TARGET_AIR_GAP_DB, 0);
  });

  it("stops at the clamp rather than fully closing a large cliff", () => {
    // Joi's real shape needs more than MAX_TILT_GAIN_DB to reach target. It is
    // deliberately not given it: past twelve decibels a shelf is amplifying
    // whatever noise lives up there as much as any signal, and a partly
    // corrected voice is a far smaller defect than a hissy one. The limit must
    // stay visible rather than being quietly raised to make a number look neat.
    const spec = tiltCorrection(voice(-26.6, 20), SR)!;
    expect(spec.gainDb).toBe(MAX_TILT_GAIN_DB);
  });

  it("says why, in the spec itself", () => {
    expect(tiltCorrection(voice(-26.6, 16.6), SR)!.reason).toMatch(/air .* below sibilance/);
  });

  it("returns null for silence and for an empty buffer", () => {
    expect(tiltCorrection(new Float32Array(SR), SR)).toBeNull();
    expect(tiltCorrection(new Float32Array(0), SR)).toBeNull();
  });
});

describe("toneFilters", () => {
  const good = { type: "peaking", frequency: 3000, gainDb: 5, q: 1.2, reason: "presence" };

  it("accepts a well-formed declaration", () => {
    expect(toneFilters([good])).toEqual([
      { type: "peaking", frequency: 3000, gainDb: 5, q: 1.2, reason: "presence" },
    ]);
  });

  it("requires a reason — an unexplained filter is how this rots", () => {
    expect(toneFilters([{ ...good, reason: "" }])).toEqual([]);
    expect(toneFilters([{ ...good, reason: undefined }])).toEqual([]);
  });

  it("bounds the gain a bundle can ask for", () => {
    expect(toneFilters([{ ...good, gainDb: MAX_TONE_GAIN_DB + 1 }])).toEqual([]);
    expect(toneFilters([{ ...good, gainDb: -(MAX_TONE_GAIN_DB + 1) }])).toEqual([]);
  });

  it("drops one malformed entry without losing the others", () => {
    // A bundle is authored elsewhere and travels; one bad filter must not
    // silence a character.
    const out = toneFilters([good, { type: "nonsense" }, null, 7,
                             { ...good, frequency: 99_000 }]);
    expect(out).toHaveLength(1);
  });

  it("treats absence as none, never as a default", () => {
    expect(toneFilters(undefined)).toEqual([]);
    expect(toneFilters(null)).toEqual([]);
    expect(toneFilters({})).toEqual([]);
  });
});

describe("shapingChain", () => {
  it("puts measured tilt before declared tone", () => {
    const chain = shapingChain(voice(-26.6, 16.6), SR,
                               [{ type: "peaking", frequency: 3000, gainDb: 5, reason: "presence" }]);
    expect(chain).toHaveLength(2);
    expect(chain[0]!.type).toBe("highshelf");
    expect(chain[1]!.type).toBe("peaking");
  });

  it("gives a catalogue voice the measured stage alone", () => {
    // Vera has no bundle and nothing to declare. She must still be corrected.
    const chain = shapingChain(voice(-26.6, 16.6), SR, undefined);
    expect(chain).toHaveLength(1);
    expect(chain[0]!.type).toBe("highshelf");
  });

  it("is empty when a good voice declares nothing", () => {
    expect(shapingChain(voice(-24, 2.6), SR, undefined)).toEqual([]);
  });
});
