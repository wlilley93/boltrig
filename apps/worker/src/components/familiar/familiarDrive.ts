// How Worker state becomes shader drive: the voice envelope, and the four
// audio channels plus the beat that the body is animated by.
//
// SPLIT OUT ON A REAL SEAM, not to satisfy the line gate. The renderer owns
// WebGL -- the context, the uniform locations, the frame loop. None of this
// touches any of that: it is arithmetic on numbers the Worker reported, and it
// is the part that changes when the voice analysis changes. Keeping it here
// means a change to how speech moves the body does not have to be made inside a
// function that also clears buffers and pushes forty uniforms.
//
// THE ENVELOPE IS THE POINT. An FFT band is noisy frame to frame even inside a
// steady vowel, so feeding one straight to the shader made the body twitch at
// frame rate -- "her pulsing is too jagged when she speaks". The obvious fix, a
// plain low-pass slow enough to stop the twitching, also blunts the attack, and
// losing the moment a syllable lands is what makes a body look disconnected
// from its own voice. Hence ASYMMETRIC: fast up, slow down.

import type { FamiliarStageState } from "./FamiliarState";

/** 0..1 warmth from local time, peaking mid-afternoon.
 *
 * Here rather than on the renderer for the same reason as everything else in
 * this file: it is a number derived from state, with no GL in it.
 *
 * Date.now is the existing visual-fixture clock seam. Reading it explicitly
 * keeps captures fixed while remaining the live clock in production; a bare
 * `new Date()` ignores a frozen Date.now implementation.
 */
export function dayWarmth(): number {
  const d = new Date(Date.now());
  const h = d.getHours() + d.getMinutes() / 60;
  return 0.15 + 0.85 * Math.max(0, Math.sin(((h - 9) / 12) * Math.PI));
}

/** Attack and release, in seconds. Attack is short enough that a syllable
 *  still arrives on time; release is long enough that a held note decays
 *  rather than snapping back between analyser frames. */
const VOICE_ATTACK = 0.045;
const VOICE_RELEASE = 0.18;

/** What the shader is driven by. xyzw of uAudio, plus the impulse channel. */
export interface FamiliarDrive {
  ax: number;
  ay: number;
  az: number;
  aw: number;
  beat: number;
}

export const SILENT_DRIVE: FamiliarDrive = { ax: 0, ay: 0, az: 0, aw: 0, beat: 0 };

/** One asymmetric envelope per named channel, stepped by the frame delta. */
export class VoiceEnvelope {
  /** Absent keys start at the first value they see, so the first frame of
   *  speech does not ramp up from silence. */
  private channels: Record<string, number> = {};

  /** Framerate-independent on purpose: a dt-based coefficient means the shape
   *  is the same at 60fps and at 30, where a fixed per-frame lerp would make
   *  the body visibly slower on a busy machine. */
  step(key: string, target: number, dt: number): number {
    const value = Number.isFinite(target) ? Math.min(1, Math.max(0, target)) : 0;
    const previous = this.channels[key];
    if (previous === undefined) {
      this.channels[key] = value;
      return value;
    }
    const tau = value > previous ? VOICE_ATTACK : VOICE_RELEASE;
    const k = 1 - Math.exp(-dt / tau);
    const next = previous + (value - previous) * k;
    this.channels[key] = next;
    return next;
  }
}

/**
 * The drive for one frame.
 *
 * Three cases, in falling order of how much the renderer actually knows: real
 * voice bands, speech with only a level, and a working turn with no voice at
 * all. The last two are oscillators because there is nothing to follow -- they
 * are a stand-in for embodiment, not embodiment.
 */
export function familiarDrive(
  state: FamiliarStageState,
  env: VoiceEnvelope,
  dt: number,
  t: number,
): FamiliarDrive {
  const { working, speaking, level, bands, onset } = state;

  if (speaking && bands && bands.length === 8) {
    // Lows pressurise the nucleus, mids move the interior, highs light the
    // surface; onset is the beat channel.
    return {
      ax: env.step("level", level ?? 0, dt),
      ay: env.step("low", (bands[0] + bands[1]) / 2, dt),
      az: env.step("mid", (bands[2] + bands[3] + bands[4]) / 3, dt),
      aw: env.step("high", (bands[5] + bands[6] + bands[7]) / 3, dt),
      // NOT smoothed: onset is an impulse and the renderer treats it as one.
      // An envelope here would turn a beat into a swell.
      beat: onset ?? 0,
    };
  }

  if (speaking) {
    const amp = 0.35 + 0.55 * (level || 0.5);
    return {
      ...SILENT_DRIVE,
      ax: amp * (0.75 + 0.25 * Math.sin(t * 3.1)),
      ay: amp * (0.6 + 0.4 * Math.sin(t * 2.2 + 1.3)),
    };
  }

  if (working) {
    return {
      ...SILENT_DRIVE,
      ax: 0.45 + 0.15 * Math.sin(t * 3.1),
      ay: 0.4 + 0.2 * Math.sin(t * 2.2 + 1.3),
    };
  }

  return SILENT_DRIVE;
}
