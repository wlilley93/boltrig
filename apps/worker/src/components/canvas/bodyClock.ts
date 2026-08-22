// The clock and the speech ring, which both particle renderers were carrying a
// copy of.
//
// It is here for size before it is here for tidiness: JarvisNeuralRenderer was
// 481 lines against the worker's 400-line floor and UltronRenderer 405, and
// neither can be pinned instead -- the structure gate re-loads its baseline from
// Git and refuses a new debt entry. But the duplication was real and the two
// copies had already drifted in their comments, which is how the next drift goes
// unnoticed.
//
// What is NOT shared is what genuinely differs per body: the energy floors, the
// onset caps, and the colour. Those stay with the body they describe.

/** How hard an onset drives the ring. The two bodies deliberately differ. */
export interface OnsetShape {
  /** Amplitude cap when a fresh front starts from silence. */
  first: number;
  /** Amplitude cap when a live ring is topped up instead. */
  top: number;
  /** How much of the onset a top-up adds. */
  gain: number;
}

export class BodyClock {
  /** Animation seconds, summed from CLAMPED frame deltas.
   *
   * NOT wall clock. A background tab stops delivering frames, so a wall-clock
   * `t` advances by the whole hidden duration and the field lurches on return
   * -- the defect every one of these renderers has carried at least once.
   * Summing the deltas actually drawn means hiding the tab pauses the animation
   * and showing it resumes, which is what a viewer expects. */
  animClock = 0;
  /** Unclamped wall-clock seconds since the last frame, for the tuning ease. */
  easeDt = 0;
  /** Seconds since the last speech onset, for the travelling wave. */
  waveT = 10;
  waveAmp = 0;
  private lastFrameAt = 0;

  /**
   * Advance to `nowMs` and return the CLAMPED simulation dt.
   *
   * TWO dt's, and conflating them made the ease frame-rate-dependent again. The
   * simulation's dt is clamped to 50ms because a longer step makes the particle
   * integrator overshoot and the field explodes -- on a slow frame the right
   * move is to advance the physics LESS than real time. The tuning ease wants
   * the opposite: it is a wall-clock animation, and clamping its dt on a machine
   * managing 7fps stretched a 1.6s ease into about 5s. Measured on swiftshader,
   * where the draw-in had not finished after eight seconds. So `easeDt` keeps
   * the wall figure and the return value is the clamped one.
   */
  advance(nowMs: number, reducedMotion: boolean): number {
    const wall = Math.max(0.001, (nowMs - this.lastFrameAt) / 1000);
    const dt = Math.min(0.05, wall);
    this.easeDt = wall;
    this.lastFrameAt = nowMs;
    if (!reducedMotion) this.animClock += dt;

    this.waveT += dt;
    // The wave DECAYS rather than being switched off, so the last syllable of a
    // sentence finishes crossing the body.
    //
    // SLOW, so the shader's reverb decay is what governs the ring. At 2.2 per
    // second this envelope was down to 11% within a second, which killed every
    // front before it could reach the shell and come back -- so the
    // reverberation existed in the arithmetic and was never seen. There are two
    // decays in this system and only one should be doing the shaping: this one
    // keeps the excitation alive, uReverb.z decides how long it rings.
    this.waveAmp *= Math.exp(-dt * 0.5);
    return dt;
  }

  /**
   * AN ONSET TOPS THE RING UP; it only restarts it once the ring has died.
   *
   * It used to reset waveT to 0 on every onset, on the reasoning that two
   * syllables should send two waves rather than one twice as strong. That is
   * right for a single travelling front and wrong now that the front REFLECTS:
   * resetting the clock puts it back at the centre before it has reached the
   * shell, so it never completes a round trip and speech pings once per syllable
   * however long the reverb tail is set to. Measured as a val trace that was flat
   * between a handful of large spikes -- the shape of a ping, not a ring.
   *
   * So a syllable arriving into a live ring re-excites it in place: the clock
   * keeps running, the front keeps bouncing, and the amplitude is topped up
   * rather than replaced. Only silence long enough for the ring to fade below a
   * quarter starts a fresh front, which is what makes the first word of a
   * sentence land differently from the fifth. The caps are the body's, because a
   * fast run of syllables topping the amplitude to full and holding it there is
   * the heave rather than the ring.
   */
  onset(amount: number, shape: OnsetShape): void {
    if (amount <= 0.35) return;
    if (this.waveAmp < 0.25) {
      this.waveT = 0;
      this.waveAmp = Math.min(shape.first, amount);
    } else if (this.waveT > 0.12) {
      this.waveAmp = Math.min(shape.top, this.waveAmp + amount * shape.gain);
    }
  }

  /**
   * A frame that will NOT be drawn still moves the origin forward.
   *
   * Without this, a suspended or hidden renderer returns to a `lastFrameAt` from
   * before it stopped, and the next real frame reads a dt of however long it was
   * away -- the same lurch animClock's clamp exists to prevent, arriving through
   * the ease instead.
   */
  markIdle(): void {
    this.lastFrameAt = performance.now();
  }
}
