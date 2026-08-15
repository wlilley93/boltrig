// Spectral shaping for spoken audio: what the voice needs, measured, plus what
// a character asks for, declared.
//
// TWO STAGES, AND THE SPLIT IS THE WHOLE DESIGN.
//
//   TILT is measured and automatic. Every voice out of this TTS is short of
//   high frequencies, and by wildly different amounts. Measured 2026-08-15,
//   5-8 kHz energy relative to the 300-1000 Hz body:
//
//       vera    -23.7 dB   (catalogue voice, not a clone)
//       joi     -26.6 dB   but -43.2 at 8-11k: a 16.6 dB cliff
//       jarvis  -34.3 dB
//       maya    -41.0 dB   seventeen dB duller than vera
//
//   A high shelf improved all four by ear, including the one that is not a
//   clone. So this is a property of the output, not a bad reference, and it
//   cannot be a per-voice table: VERA HAS NO BUNDLE. She is a name in the
//   runtime catalogue with nothing to declare on, and so is every voice a user
//   picks from it later. Configuration cannot reach her. Measurement can.
//
//   TONE is declared and optional. A character may ask for shaping that is
//   about who they are rather than about a deficiency -- presence for
//   consonant clarity, a cut where a voice sounds boxy. That is not derivable,
//   because it is a judgement rather than a defect, so the character brings it
//   and absence means none. It never substitutes: no declaration yields the
//   measured stages alone, exactly as for a catalogue voice.
//
// The corner frequency is why tilt cannot be one constant either. Vera's
// sibilance peaks at 6 kHz, so a 6 kHz shelf boosts her "sss" head-on while
// the same filter merely adds air to Maya. The corner is therefore placed
// ABOVE each utterance's own measured sibilance peak.
//
// This module is pure and knows nothing about Web Audio. It returns a
// description of a chain; the caller builds the nodes. That keeps it testable
// without a browser and keeps the policy in one readable place.

/** Where a voice should sit: air within this of the sibilant band. */
export const TARGET_AIR_GAP_DB = 3;

/** Bounds on the automatic correction. It fixes a tilt; it is not an effect. */
export const MAX_TILT_GAIN_DB = 12;
export const MIN_TILT_GAIN_DB = 0;

/** A character's declared shaping may not exceed this in either direction. */
export const MAX_TONE_GAIN_DB = 12;

const BODY = [300, 1000] as const;
const SIBILANT = [5000, 8000] as const;
const AIR = [8000, 11000] as const;

/** Narrow bands the sibilance peak is searched over. */
const PEAK_BANDS: readonly (readonly [number, number])[] = [
  [3500, 4500], [4500, 5500], [5500, 6500], [6500, 7500],
  [7500, 8500], [8500, 9500], [9500, 11000],
];

export type FilterKind = "peaking" | "highshelf" | "lowshelf";

export interface FilterSpec {
  type: FilterKind;
  frequency: number;
  gainDb: number;
  q?: number;
  /** Why this filter exists. Required on declared tone; set by us on tilt. */
  reason: string;
}

const dB = (a: number): number => (a > 0 ? 20 * Math.log10(a) : Number.NEGATIVE_INFINITY);
const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));

const FRAME = 2048;              // ~85 ms at 24 kHz: enough resolution at 300 Hz
const HOP = 1024;
const VOICED_GATE_DB = 30;       // frames this far below the loudest are silence

/** In-place iterative radix-2 FFT. `re`/`im` must be a power-of-two length. */
function fft(re: Float64Array, im: Float64Array): void {
  const n = re.length;
  for (let i = 1, j = 0; i < n; i += 1) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) {
      [re[i], re[j]] = [re[j] as number, re[i] as number];
      [im[i], im[j]] = [im[j] as number, im[i] as number];
    }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = (-2 * Math.PI) / len;
    const wr = Math.cos(ang), wi = Math.sin(ang);
    for (let i = 0; i < n; i += len) {
      let cr = 1, ci = 0;
      for (let k = 0; k < len / 2; k += 1) {
        const ar = re[i + k] as number, ai = im[i + k] as number;
        const br = re[i + k + len / 2] as number, bi = im[i + k + len / 2] as number;
        const tr = br * cr - bi * ci, ti = br * ci + bi * cr;
        re[i + k] = ar + tr; im[i + k] = ai + ti;
        re[i + k + len / 2] = ar - tr; im[i + k + len / 2] = ai - ti;
        const ncr = cr * wr - ci * wi;
        ci = cr * wi + ci * wr; cr = ncr;
      }
    }
  }
}

/**
 * Mean magnitude spectrum over the frames that carry speech.
 *
 * Gated, because sibilance is BURSTY -- it lives in a small minority of frames,
 * and averaging over silence dilutes it differently from the vowel bands,
 * which biases every comparison between them.
 */
function voicedSpectrum(samples: Float32Array): Float64Array | null {
  if (samples.length < FRAME) return null;
  const frames: number[] = [];
  for (let s = 0; s + FRAME <= samples.length; s += HOP) {
    let sum = 0;
    for (let i = s; i < s + FRAME; i += 1) { const v = samples[i] ?? 0; sum += v * v; }
    frames.push(Math.sqrt(sum / FRAME));
  }
  const loudest = Math.max(...frames);
  if (loudest <= 0) return null;
  const gate = loudest * 10 ** (-VOICED_GATE_DB / 20);
  const mag = new Float64Array(FRAME / 2 + 1);
  let kept = 0;
  for (let f = 0; f < frames.length; f += 1) {
    if ((frames[f] ?? 0) < gate) continue;
    const start = f * HOP;
    const re = new Float64Array(FRAME);
    const im = new Float64Array(FRAME);
    for (let i = 0; i < FRAME; i += 1) {
      // Hann, to stop a bin's energy smearing across the band boundaries the
      // whole measurement is defined by.
      const w = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (FRAME - 1));
      re[i] = (samples[start + i] ?? 0) * w;
    }
    fft(re, im);
    for (let b = 0; b < mag.length; b += 1) {
      mag[b] = (mag[b] as number) + Math.hypot(re[b] as number, im[b] as number);
    }
    kept += 1;
  }
  if (kept === 0) return null;
  for (let b = 0; b < mag.length; b += 1) mag[b] = (mag[b] as number) / kept;
  return mag;
}

/**
 * RMS level of one band of the voiced spectrum, in dB.
 *
 * AN FFT, NOT A FILTER, and that was measured rather than assumed. A cascade of
 * band-pass biquads was tried first and could not reproduce these numbers: on
 * real speech it read Maya's sibilance-to-air gap as 7.8 dB where the transform
 * reads 1.3, which would have applied six decibels of unwanted lift to the one
 * voice that needs none. Adding stages made it worse, not better, because the
 * two methods differ in what they average over rather than in selectivity.
 * The targets in this file come from the transform, so the transform is what
 * has to run.
 */
export function bandDb(samples: Float32Array, sampleRate: number,
                       low: number, high: number): number {
  if (samples.length === 0 || high <= low) return Number.NEGATIVE_INFINITY;
  const mag = voicedSpectrum(samples);
  if (!mag) return Number.NEGATIVE_INFINITY;
  const binHz = sampleRate / FRAME;
  let sum = 0, n = 0;
  for (let b = 0; b < mag.length; b += 1) {
    const hz = b * binHz;
    if (hz < low || hz >= high) continue;
    const v = mag[b] as number;
    sum += v * v; n += 1;
  }
  if (n === 0) return Number.NEGATIVE_INFINITY;
  return dB(Math.sqrt(sum / n));
}

/**
 * Where this utterance's sibilance sits, in Hz.
 *
 * Measured rather than assumed because it moves: Vera peaks at 6 kHz and a
 * shelf cornered there amplifies her "sss" instead of adding air above it.
 * Returns the centre of the strongest narrow band between 3.5 and 11 kHz.
 */
export function sibilancePeakHz(samples: Float32Array, sampleRate: number): number {
  let best = PEAK_BANDS[0] as readonly [number, number];
  let bestDb = Number.NEGATIVE_INFINITY;
  for (const band of PEAK_BANDS) {
    // Nyquist: a band the sample rate cannot represent must not win by
    // measuring the filter's own ringing.
    if (band[1] > sampleRate / 2) continue;
    const level = bandDb(samples, sampleRate, band[0], band[1]);
    if (level > bestDb) { bestDb = level; best = band; }
  }
  return (best[0] + best[1]) / 2;
}

/**
 * The automatic tilt correction for this audio, or null when none is wanted.
 *
 * Null rather than a 0 dB filter so the caller builds no node at all: a voice
 * that already has air should be left completely alone, not routed through an
 * identity filter that only adds a place for a bug to live.
 */
export function tiltCorrection(samples: Float32Array,
                               sampleRate: number): FilterSpec | null {
  if (samples.length === 0) return null;
  const body = bandDb(samples, sampleRate, BODY[0], BODY[1]);
  const sibilant = bandDb(samples, sampleRate, SIBILANT[0], SIBILANT[1]);
  const air = bandDb(samples, sampleRate, AIR[0], AIR[1]);
  if (![body, sibilant, air].every(Number.isFinite)) return null;

  // The deficit is measured against the SIBILANT band, not against a fixed
  // dBFS figure, so a quiet utterance is not mistaken for a dull one. Loudness
  // is a separate stage and must not leak into this one.
  const gap = sibilant - air;
  const wanted = clamp(gap - TARGET_AIR_GAP_DB, MIN_TILT_GAIN_DB, MAX_TILT_GAIN_DB);
  if (wanted <= 0.5) return null;

  // Above the peak, never on it. A shelf cornered at the sibilance peak lifts
  // the "sss" as much as the air over it, which is how a correction becomes a
  // harshness.
  const peak = sibilancePeakHz(samples, sampleRate);
  const corner = Math.min(peak * 1.35, sampleRate / 2 - 500);
  return {
    type: "highshelf",
    frequency: Math.round(corner),
    gainDb: Number(wanted.toFixed(2)),
    reason: `air ${gap.toFixed(1)} dB below sibilance; corner set above the ` +
            `${Math.round(peak)} Hz peak`,
  };
}

/**
 * A character's declared tone, validated.
 *
 * Untrusted input: a bundle is authored elsewhere and travels between installs,
 * so every field is checked and anything malformed is DROPPED rather than
 * throwing. One bad entry must not silence a character -- the same rule the
 * voice-id map already follows.
 */
export function toneFilters(declared: unknown): FilterSpec[] {
  if (!Array.isArray(declared)) return [];
  const out: FilterSpec[] = [];
  for (const raw of declared) {
    if (!raw || typeof raw !== "object") continue;
    const entry = raw as Record<string, unknown>;
    const type = entry.type;
    const frequency = entry.frequency;
    const gainDb = entry.gainDb;
    const reason = entry.reason;
    if (type !== "peaking" && type !== "highshelf" && type !== "lowshelf") continue;
    if (typeof frequency !== "number" || !Number.isFinite(frequency)
        || frequency < 20 || frequency > 20000) continue;
    if (typeof gainDb !== "number" || !Number.isFinite(gainDb)
        || Math.abs(gainDb) > MAX_TONE_GAIN_DB) continue;
    // A declared filter with no stated why is how a measured correction rots
    // into an undocumented fudge. Required, and enforced here as well as in
    // the schema, because the schema does not run in the player.
    if (typeof reason !== "string" || !reason.trim()) continue;
    const q = typeof entry.q === "number" && Number.isFinite(entry.q)
      ? clamp(entry.q, 0.1, 10) : undefined;
    out.push({ type, frequency, gainDb, reason: reason.trim(), ...(q ? { q } : {}) });
  }
  return out;
}

/**
 * The full shaping chain for one utterance: measured tilt, then declared tone.
 *
 * Order matters. Tilt corrects what the engine failed to produce; tone shapes
 * what the character wants on top of a corrected signal. Reversing them would
 * make a character's declaration depend on how dull that day's render was.
 */
export function shapingChain(samples: Float32Array, sampleRate: number,
                             declaredTone?: unknown): FilterSpec[] {
  const tilt = tiltCorrection(samples, sampleRate);
  return [...(tilt ? [tilt] : []), ...toneFilters(declaredTone)];
}
