// The travelling wave a voice sets going in a particle body, and the eight
// bands it is driven by. One mechanism, two tunings.
//
// WHY IT IS SHARED. JarvisNeuralRenderer and UltronRenderer each carried this
// block, and Ultron's copy said so: "See the same block in JarvisNeuralRenderer
// for why". Two copies of a rule is one copy and a disagreement waiting to
// happen, and the reasoning below is the expensive part - it was arrived at
// from a measured val trace, and it is not obvious enough to re-derive.
//
// AN ONSET TOPS THE RING UP; it only restarts it once the ring has died.
//
// It used to reset the clock to 0 on every onset, on the reasoning that two
// syllables should send two waves rather than one twice as strong. That is
// right for a single travelling front and wrong now that the front REFLECTS:
// resetting the clock puts it back at the centre before it has reached the
// shell, so it never completes a round trip and speech pings once per syllable
// however long the reverb tail is set to. Measured as a val trace that was flat
// between a handful of large spikes -- the shape of a ping, not a ring.
//
// So a syllable arriving into a live ring re-excites it in place: the clock
// keeps running, the front keeps bouncing, and the amplitude is topped up
// rather than replaced. Only silence long enough for the ring to fade below a
// quarter starts a fresh front, which is what makes the first word of a
// sentence land differently from the fifth.

const SILENT_BANDS = new Float32Array(8);

/** What differs between the bodies. Everything else about the wave does not. */
export interface VoiceWaveTuning {
  /** Ceiling on a FRESH front, started only out of silence. */
  freshCap: number;
  /** Ceiling on a top-up into a ring that is still alive. */
  topUpCap: number;
  /** How much of an onset a top-up adds. */
  topUpGain: number;
}

/** Jarvis tops up below full: a fast run of syllables kept pinning Ultron's to
 *  1 and holding it there, which is the heave rather than the ring. */
export const JARVIS_WAVE: VoiceWaveTuning = { freshCap: 0.85, topUpCap: 0.72, topUpGain: 0.4 };
export const ULTRON_WAVE: VoiceWaveTuning = { freshCap: 1, topUpCap: 1, topUpGain: 0.6 };

export class VoiceWave {
  /** Seconds since the last speech onset. Starts past any reverb tail. */
  t = 10;
  amp = 0;
  readonly bands = new Float32Array(8);

  constructor(private readonly tuning: VoiceWaveTuning) {}

  /** Take a stage onset. Values at or below 0.35 are not speech. */
  onset(value: unknown): void {
    const onset = typeof value === "number" ? value : 0;
    if (onset <= 0.35) return;
    if (this.amp < 0.25) {
      this.t = 0;
      this.amp = Math.min(this.tuning.freshCap, onset);
    } else if (this.t > 0.12) {
      this.amp = Math.min(this.tuning.topUpCap, this.amp + onset * this.tuning.topUpGain);
    }
  }

  /** Eight 0..1 bands, or silence when the stage has none to give. */
  setBands(bands: ArrayLike<number> | null | undefined): void {
    if (bands && bands.length === 8) {
      for (let i = 0; i < 8; i++) this.bands[i] = Math.min(1, Math.max(0, bands[i]));
    } else {
      this.bands.set(SILENT_BANDS);
    }
  }

  /**
   * Advance one frame.
   *
   * The wave DECAYS rather than being switched off, so the last syllable of a
   * sentence finishes crossing the body. Slow, at 0.5 per second, so the
   * shader's reverb decay is what governs the ring: at 2.2 this envelope was
   * down to 11% within a second, which killed every front before it could
   * reach the shell and come back, so the reverberation existed in the
   * arithmetic and was never seen. There are two decays in this system and
   * only one of them should be doing the shaping.
   */
  advance(dt: number): void {
    this.t += dt;
    this.amp *= Math.exp(-dt * 0.5);
  }
}
