/**
 * The spectral measurement half of the voice tone chain.
 *
 * Separated from voiceTone.ts because the two answer different questions and
 * together they broke the 400-line file ceiling. This file measures what the
 * signal IS -- band energies, the sibilance peak, the voiced-frame spectrum
 * behind both. voiceTone.ts decides what to DO about it. Nothing here knows
 * about filters, and nothing there knows about an FFT.
 */

const FRAME = 2048;              // ~85 ms at 24 kHz: enough resolution at 300 Hz
const HOP = 1024;
const VOICED_GATE_DB = 30;       // frames this far below the loudest are silence

const dB = (a: number): number => (a > 0 ? 20 * Math.log10(a) : Number.NEGATIVE_INFINITY);

const PEAK_BANDS: readonly (readonly [number, number])[] = [
  [3500, 4500], [4500, 5500], [5500, 6500], [6500, 7500],
  [7500, 8500], [8500, 9500], [9500, 11000],
];


/**
 * Permute both arrays into bit-reversed order, in place.
 *
 * The first of an FFT's two phases, and a real seam rather than a line drawn to
 * satisfy a limit: this is a pure index permutation with no arithmetic, while
 * the butterflies below are all arithmetic and no permutation. Together they
 * measured complexity 20 against a ceiling of 15, and the algorithm is not the
 * kind of thing to make less legible to get a number down.
 */
function bitReverse(re: Float64Array, im: Float64Array): void {
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
}

/** In-place radix-2 Cooley-Tukey. Length must be a power of two. */
function fft(re: Float64Array, im: Float64Array): void {
  const n = re.length;
  bitReverse(re, im);
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
/** Per-frame RMS across the signal, one value per hop. */
function frameEnergies(samples: Float32Array): number[] {
  const frames: number[] = [];
  for (let s = 0; s + FRAME <= samples.length; s += HOP) {
    let sum = 0;
    for (let i = s; i < s + FRAME; i += 1) { const v = samples[i] ?? 0; sum += v * v; }
    frames.push(Math.sqrt(sum / FRAME));
  }
  return frames;
}

/**
 * One Hann-windowed frame, transformed.
 *
 * Hann, to stop a bin's energy smearing across the band boundaries the whole
 * measurement is defined by.
 */
function windowedFft(samples: Float32Array, start: number): { re: Float64Array; im: Float64Array } {
  const re = new Float64Array(FRAME);
  const im = new Float64Array(FRAME);
  for (let i = 0; i < FRAME; i += 1) {
    const w = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (FRAME - 1));
    re[i] = (samples[start + i] ?? 0) * w;
  }
  fft(re, im);
  return { re, im };
}

function voicedSpectrum(samples: Float32Array): Float64Array | null {
  if (samples.length < FRAME) return null;
  const frames = frameEnergies(samples);
  const loudest = Math.max(...frames);
  if (loudest <= 0) return null;
  const gate = loudest * 10 ** (-VOICED_GATE_DB / 20);
  const mag = new Float64Array(FRAME / 2 + 1);
  let kept = 0;
  for (let f = 0; f < frames.length; f += 1) {
    if ((frames[f] ?? 0) < gate) continue;
    const start = f * HOP;
    const { re, im } = windowedFft(samples, start);
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
