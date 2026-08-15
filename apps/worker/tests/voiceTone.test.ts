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

/** Sum of sines at given (hz, dBFS-RMS) pairs — a spectrum with known answers. */
function mix(parts: readonly (readonly [number, number])[], seconds = 1): Float32Array {
  const n = Math.floor(SR * seconds);
  const out = new Float32Array(n);
  for (const [hz, db] of parts) {
    const amp = 10 ** (db / 20) * Math.SQRT2;
    for (let i = 0; i < n; i += 1) out[i] += amp * Math.sin((2 * Math.PI * hz * i) / SR);
  }
  return out;
}

/** A voice-shaped spectrum: body, sibilance, air — each independently settable. */
const voice = (bodyDb: number, sibDb: number, airDb: number): Float32Array =>
  mix([[500, bodyDb], [6000, sibDb], [9500, airDb]]);

describe("bandDb", () => {
  it("finds a tone in its own band and not in another", () => {
    const s = mix([[600, -20]]);
    expect(bandDb(s, SR, 300, 1000)).toBeGreaterThan(-26);
    expect(bandDb(s, SR, 5000, 8000)).toBeLessThan(-55);
  });

  it("is monotonic in level", () => {
    const loud = bandDb(mix([[600, -12]]), SR, 300, 1000);
    const quiet = bandDb(mix([[600, -30]]), SR, 300, 1000);
    expect(loud - quiet).toBeCloseTo(18, 0);
  });

  it("returns -Infinity for silence rather than a floor value", () => {
    expect(bandDb(new Float32Array(SR), SR, 300, 1000)).toBe(Number.NEGATIVE_INFINITY);
    expect(bandDb(new Float32Array(0), SR, 300, 1000)).toBe(Number.NEGATIVE_INFINITY);
  });
});

describe("sibilancePeakHz", () => {
  it("locates the peak where the energy actually is", () => {
    expect(sibilancePeakHz(mix([[6000, -20]]), SR)).toBeCloseTo(6000, -2);
    expect(sibilancePeakHz(mix([[9000, -20]]), SR)).toBeCloseTo(9000, -2);
  });

  it("never returns a band the sample rate cannot represent", () => {
    // At 16 kHz, Nyquist is 8 kHz. Bands above it would otherwise "win" by
    // measuring the filter's own ringing rather than any signal.
    const peak = sibilancePeakHz(mix([[6000, -20]]), 16_000);
    expect(peak).toBeLessThan(8_000);
  });
});

describe("tiltCorrection", () => {
  it("does nothing to a voice that already has air", () => {
    // vera and maya measure a 1-3 dB gap natively; nothing to fix.
    expect(tiltCorrection(voice(-15, -30, -31), SR)).toBeNull();
  });

  it("corrects a cliff, and by about the measured deficit", () => {
    // joi's shape: sibilance present, air 16 dB below it.
    const spec = tiltCorrection(voice(-15, -26, -42), SR);
    expect(spec).not.toBeNull();
    expect(spec!.type).toBe("highshelf");
    expect(spec!.gainDb).toBeGreaterThan(8);
    expect(spec!.gainDb).toBeLessThanOrEqual(MAX_TILT_GAIN_DB);
  });

  it("puts the corner ABOVE the sibilance peak, never on it", () => {
    // THE BUG THIS PREVENTS. Vera's sibilance peaks at 6 kHz; a shelf cornered
    // there boosts her "sss" instead of the air above it, which is audible as
    // harshness rather than as presence.
    const spec = tiltCorrection(mix([[500, -15], [6000, -26], [9500, -42]]), SR);
    expect(spec).not.toBeNull();
    expect(spec!.frequency).toBeGreaterThan(6000);
  });

  it("never boosts, only ever lifts toward the target", () => {
    // An air-rich voice must not be attenuated into the target from above.
    const spec = tiltCorrection(voice(-15, -40, -20), SR);
    expect(spec).toBeNull();
  });

  it("leaves the target gap rather than flattening the spectrum", () => {
    // A gap inside the clamp, so the arithmetic is what is under test.
    const s = voice(-15, -30, -40);
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
    const spec = tiltCorrection(voice(-15, -26, -45), SR)!;
    expect(spec.gainDb).toBe(MAX_TILT_GAIN_DB);
  });

  it("says why, in the spec itself", () => {
    expect(tiltCorrection(voice(-15, -26, -42), SR)!.reason).toMatch(/air .* below sibilance/);
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
    const chain = shapingChain(voice(-15, -26, -42), SR,
                               [{ type: "peaking", frequency: 3000, gainDb: 5, reason: "presence" }]);
    expect(chain).toHaveLength(2);
    expect(chain[0]!.type).toBe("highshelf");
    expect(chain[1]!.type).toBe("peaking");
  });

  it("gives a catalogue voice the measured stage alone", () => {
    // Vera has no bundle and nothing to declare. She must still be corrected.
    const chain = shapingChain(voice(-15, -26, -42), SR, undefined);
    expect(chain).toHaveLength(1);
    expect(chain[0]!.type).toBe("highshelf");
  });

  it("is empty when a good voice declares nothing", () => {
    expect(shapingChain(voice(-15, -30, -31), SR, undefined)).toEqual([]);
  });
});
