// One loudness policy, applied where the audio ARRIVES rather than where it is
// made.
//
// Every provider hands us a different level. Measured on Pocket TTS alone
// (2026-08-15, five renders of one line through eight Maya registers): speech
// level spanned 3.2 dB between registers, and 4.4 dB between renders of the
// SAME register. ElevenLabs and Fish sit somewhere else again. So there is no
// per-voice constant that fixes this -- the within-voice spread is wider than
// the between-voice spread, and a static gain table would correct the smaller
// half while leaving the larger one in place.
//
// Normalising here instead of in pocket-voice is deliberate:
//
//   * pocket-voice serves boltrig, maya-player and anything else. Loudness is a
//     PLAYBACK concern, and baking one policy into the synth imposes it on every
//     consumer.
//   * doing it per provider means doing it three times and drifting twice.
//   * this is the only layer that sees every voice from every provider, which is
//     exactly what "sound the same" requires.
//
// It costs nothing in latency. Both playback paths already hold decoded samples
// before they schedule them, so the gain is a scalar multiply on a node that was
// going to exist anyway.

/**
 * Target speech level, dBFS.
 *
 * Chosen to normalise DOWNWARD from what was measured rather than upward.
 * Pocket TTS peaks reached -0.4 dBFS, so lifting quiet registers toward a
 * broadcast-style -14 would clip the loud ones and require a limiter to undo;
 * -16 sits just below the quietest register measured (-16.6) so almost every
 * utterance is attenuated slightly and none is pushed into the ceiling.
 */
export const TARGET_SPEECH_DBFS = -16;

/**
 * Never let a normalised utterance peak above this.
 *
 * The gain is derived from an AVERAGE, so a clip with one loud transient can
 * still be asked for more gain than its peak can take. This is the backstop,
 * and it wins over the target: a slightly quiet line is a much smaller defect
 * than a clipped one.
 */
export const PEAK_CEILING_DBFS = -1;

/**
 * How far the gain may travel, in dB.
 *
 * A bound rather than free rein, because the input is untrusted: an empty
 * buffer, a near-silent one, or a provider returning noise would otherwise ask
 * for enormous gain and produce a very loud surprise. Clamping means a
 * pathological input plays at roughly its own level instead.
 */
export const MAX_GAIN_DB = 12;
export const MIN_GAIN_DB = -12;

const FRAME = 1024;

/**
 * How far below the loudest frame still counts as speech, in dB.
 *
 * Plain RMS over the whole buffer measures the SILENCE too, so a line with a
 * long tail reads as quieter than the same line without one and gets boosted
 * for having ended with a pause. This gates on the signal instead.
 *
 * A QUANTILE WAS TRIED HERE FIRST AND WAS WRONG. "Mean of the loudest 40% of
 * frames" sounds equivalent and is not: when a clip is more than 60% silence
 * the 60th-percentile value IS zero, every frame passes `>= cut`, and the
 * measure silently degrades to the plain RMS it was meant to replace.
 * Measured, that read one second of -20 dBFS speech padded to three seconds as
 * -29.4 dBFS. A gate relative to the peak frame cannot fail that way, because
 * it is defined by the signal rather than by how much silence surrounds it.
 */
const SPEECH_GATE_DB = 30;

const dB = (amplitude: number): number =>
  amplitude > 0 ? 20 * Math.log10(amplitude) : Number.NEGATIVE_INFINITY;
const fromDb = (decibels: number): number => 10 ** (decibels / 20);

/** RMS of the frames that carry speech, in dBFS. -Infinity for silence. */
export function speechLevelDb(samples: Float32Array): number {
  if (samples.length === 0) return Number.NEGATIVE_INFINITY;
  const frames: number[] = [];
  for (let start = 0; start + FRAME <= samples.length; start += FRAME) {
    let sum = 0;
    for (let i = start; i < start + FRAME; i += 1) {
      const s = samples[i] ?? 0;
      sum += s * s;
    }
    frames.push(Math.sqrt(sum / FRAME));
  }
  if (frames.length === 0) {
    // Shorter than one frame: measure the whole thing rather than report
    // silence. A 20 ms chunk is a real signal, just a small one.
    let sum = 0;
    for (let i = 0; i < samples.length; i += 1) {
      const s = samples[i] ?? 0;
      sum += s * s;
    }
    return dB(Math.sqrt(sum / samples.length));
  }
  const loudest = Math.max(...frames);
  if (loudest <= 0) return Number.NEGATIVE_INFINITY;
  const gate = loudest * fromDb(-SPEECH_GATE_DB);
  const voiced = frames.filter((f) => f >= gate);
  const mean = voiced.reduce((a, b) => a + b, 0) / (voiced.length || 1);
  return dB(mean);
}

export function peakDb(samples: Float32Array): number {
  let peak = 0;
  for (let i = 0; i < samples.length; i += 1) {
    const a = Math.abs(samples[i] ?? 0);
    if (a > peak) peak = a;
  }
  return dB(peak);
}

/**
 * The linear gain to apply to this audio, or 1 when it cannot be measured.
 *
 * Returns 1 rather than throwing on silence or an empty buffer: an unmeasurable
 * utterance should play untouched, not be silenced or amplified into noise.
 */
export function normalisationGain(samples: Float32Array): number {
  const level = speechLevelDb(samples);
  if (!Number.isFinite(level)) return 1;
  const wanted = Math.min(MAX_GAIN_DB, Math.max(MIN_GAIN_DB, TARGET_SPEECH_DBFS - level));
  const peak = peakDb(samples);
  // Peak guard, applied AFTER the clamp so it can only ever reduce.
  const headroom = Number.isFinite(peak) ? PEAK_CEILING_DBFS - peak : wanted;
  return fromDb(Math.min(wanted, headroom));
}

/** Float samples from interleaved-mono 16-bit PCM, for the streamed path. */
export function pcm16ToFloat(pcm: Int16Array): Float32Array {
  const out = new Float32Array(pcm.length);
  for (let i = 0; i < pcm.length; i += 1) out[i] = (pcm[i] ?? 0) / 0x8000;
  return out;
}

/**
 * Holds ONE gain for the length of an utterance.
 *
 * The streamed path receives 20-100 ms chunks, and normalising each one
 * independently is the classic auto-gain artefact: loudness pumps inside a
 * single sentence, which sounds far worse than the inconsistency being fixed.
 * So the first chunk that carries a measurable signal sets the gain, and every
 * later chunk of the same utterance reuses it. `reset()` is called at an
 * utterance boundary, not per chunk.
 */
export class UtteranceGain {
  private gain: number | null = null;

  reset(): void {
    this.gain = null;
  }

  /** The gain for this utterance, deciding it from `samples` if not yet set. */
  forChunk(samples: Float32Array): number {
    if (this.gain !== null) return this.gain;
    const level = speechLevelDb(samples);
    // A leading chunk of near-silence must not fix the gain for the whole
    // utterance -- wait for one that actually has speech in it.
    if (!Number.isFinite(level) || level < -50) return 1;
    this.gain = normalisationGain(samples);
    return this.gain;
  }

  get decided(): boolean {
    return this.gain !== null;
  }
}
