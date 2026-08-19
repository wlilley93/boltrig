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
//
// EVERY CONSTANT IN HERE IS NOW A DIAL. The attack and release were literals,
// and so were the oscillator's depth and rate -- numbers nobody could revisit
// without editing a frame loop and reloading the app. They live in
// canvas/familiarTuning.ts, which is what puts this body in the shader bench
// beside Jarvis and Ultron with the same sliders and the same LFO sweeps.

import type { FamiliarTuning, VoiceRamp } from "../canvas/familiarTuning";
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
export function dayWarmth(tuning: FamiliarTuning): number {
  const d = new Date(Date.now());
  const h = d.getHours() + d.getMinutes() / 60;
  const [floor, span] = tuning.daylight;
  return floor + span * Math.max(0, Math.sin(((h - 9) / 12) * Math.PI));
}

/** What the shader is driven by. xyzw of uAudio, plus the impulse channel. */
export interface FamiliarDrive {
  ax: number;
  ay: number;
  az: number;
  aw: number;
  beat: number;
  /**
   * 0..1 how engaged she is with whoever is in front of her.
   *
   * Drives gaze and the attention lift rather than any audio channel, which is
   * what keeps listening from looking like quiet speaking: attending to a voice
   * is where you are LOOKING, not how hard you are moving.
   */
  attend: number;
}

export const SILENT_DRIVE: FamiliarDrive = { ax: 0, ay: 0, az: 0, aw: 0, beat: 0, attend: 0 };

const clamp01 = (v: number | undefined) =>
  typeof v === "number" && Number.isFinite(v) ? Math.min(1, Math.max(0, v)) : 0;

/** `base + perVoice * energy`, bounded. The shader clamps too, but a value
 *  arriving already in range is one less place for a tuning to look broken. */
const ramp = (r: VoiceRamp, energy: number): number => clamp01(r[0] + r[1] * energy);

/** One asymmetric envelope per named channel, stepped by the frame delta. */
export class VoiceEnvelope {
  /** Absent keys start at the first value they see, so the first frame of
   *  speech does not ramp up from silence. */
  private channels: Record<string, number> = {};

  /** Framerate-independent on purpose: a dt-based coefficient means the shape
   *  is the same at 60fps and at 30, where a fixed per-frame lerp would make
   *  the body visibly slower on a busy machine. */
  step(key: string, target: number, dt: number, attack: number, release: number): number {
    const value = clamp01(target);
    const previous = this.channels[key];
    if (previous === undefined) {
      this.channels[key] = value;
      return value;
    }
    const tau = Math.max(0.005, value > previous ? attack : release);
    const k = 1 - Math.exp(-dt / tau);
    const next = previous + (value - previous) * k;
    this.channels[key] = next;
    return next;
  }
}

/**
 * The beat channel: instant attack, exponential tail.
 *
 * NOT SMOOTHED BY VoiceEnvelope, and no longer raw either. Onset is positive
 * spectral flux -- a per-frame DIFFERENCE -- so it spikes on the frame a
 * syllable lands and collapses to zero on the next one even while the vowel is
 * still going. Fed straight through at the ~30Hz the analyser is sampled at,
 * and multiplied hard in five places inside the shader, that is a strobe.
 *
 * An envelope would be the wrong fix in the other direction: attack smoothing
 * turns a beat into a swell, which is precisely the moment being animated. So
 * the rise is instantaneous and only the fall is shaped, which is what a
 * syllable actually looks like -- it lands, then it rings out.
 */
export class BeatImpulse {
  private value = 0;

  step(onset: number, dt: number, gain: number, decay: number): number {
    const target = clamp01(onset) * gain;
    const decayed = this.value * Math.exp(-dt / Math.max(0.01, decay));
    this.value = Math.max(target, decayed);
    return Math.min(1, this.value);
  }
}

/**
 * How much of this frame is voice rather than floor.
 *
 * ONE GAIN FOR ALL FOUR CHANNELS, computed from the level. Gating each band
 * against its own floor would let a quiet frame through in whichever band
 * happened to be noisiest, which smears the spectrum and produces exactly the
 * twitch the gate exists to remove -- the body would answer the noise floor's
 * shape instead of a voice. Judging the whole frame once and scaling everything
 * by that verdict keeps the spectrum intact and only ever removes silence.
 */
function voiceGain(level: number, tuning: FamiliarTuning): number {
  const [floor, knee] = tuning.voiceGate;
  if (level <= floor) return 0;
  const t = Math.min(1, (level - floor) / Math.max(1e-4, knee));
  // Smoothstep rather than linear: a linear knee opens with a corner in it, and
  // a corner in a gain is audible as a click and visible as a flinch.
  return t * t * (3 - 2 * t);
}

/** The eight bands folded into the three the shader reads. */
function fold(bands: number[]): { low: number; mid: number; high: number } {
  return {
    low: (bands[0] + bands[1]) / 2,
    mid: (bands[2] + bands[3] + bands[4]) / 3,
    high: (bands[5] + bands[6] + bands[7]) / 3,
  };
}

/**
 * Speech with a real spectrum: the one path that is embodiment rather than a
 * stand-in for it.
 *
 * Lows pressurise the nucleus, mids move the interior, highs light the surface.
 * That mapping is the shader's, not a choice made here -- see familiar.frag,
 * where uAudio.y drives the breath and uAudio.w the filaments.
 */
function spokenDrive(
  state: FamiliarStageState,
  env: VoiceEnvelope,
  beat: BeatImpulse,
  dt: number,
  tuning: FamiliarTuning,
): FamiliarDrive {
  const bands = state.bands as number[];
  const [attack, release] = tuning.voiceEnv;
  const level = clamp01(state.level);
  const gain = voiceGain(level, tuning);
  const { low, mid, high } = fold(bands);
  const [beatGain, beatDecay] = tuning.beat;
  return {
    ax: ramp(tuning.voiceLevel, env.step("level", level * gain, dt, attack, release)),
    ay: ramp(tuning.voiceLow, env.step("low", low * gain, dt, attack, release)),
    az: ramp(tuning.voiceMid, env.step("mid", mid * gain, dt, attack, release)),
    aw: ramp(tuning.voiceHigh, env.step("high", high * gain, dt, attack, release)),
    // The onset is gated by the same verdict: a flux spike inside a silence is
    // the noise floor moving, and flaring on it is the twitch at its loudest.
    beat: beat.step((state.onset ?? 0) * gain, dt, beatGain, beatDecay),
    attend: 1,
  };
}

/** A body oscillating because there is nothing to follow. A stand-in for
 *  embodiment, not embodiment -- which is why it is one shape with two dials
 *  rather than four hand-tuned waveforms. */
function pulseDrive(tuning: FamiliarTuning, t: number): FamiliarDrive {
  const [depth, rate] = tuning.idlePulse;
  if (depth <= 0) return SILENT_DRIVE;
  return {
    ...SILENT_DRIVE,
    ax: clamp01(depth * (3 + Math.sin(t * rate * 6.4))),
    ay: clamp01(depth * (2.7 + 1.3 * Math.sin(t * rate * 4.5 + 1.3))),
  };
}

/**
 * The drive for one frame.
 *
 * Ordered by how much the renderer actually knows, not by how the modes are
 * spelled: real bands beat a bare level, and a bare level beats an oscillator.
 */
export function familiarDrive(
  state: FamiliarStageState,
  smoothers: { env: VoiceEnvelope; beat: BeatImpulse },
  dt: number,
  t: number,
  tuning: FamiliarTuning,
): FamiliarDrive {
  const { mode, bands } = state;

  if (mode === "speaking" && bands && bands.length === 8) {
    return spokenDrive(state, smoothers.env, smoothers.beat, dt, tuning);
  }

  if (mode === "speaking") {
    // No spectrum, only a level: the oscillator scaled by how loud she is. It
    // is the honest degradation -- it moves with the voice's volume and knows
    // nothing about its shape, which is exactly what the host reported.
    const amp = 0.35 + 0.55 * (state.level || 0.5);
    return {
      ...SILENT_DRIVE,
      ax: ramp(tuning.voiceLevel, amp * (0.75 + 0.25 * Math.sin(t * 3.1))),
      ay: ramp(tuning.voiceLow, amp * (0.6 + 0.4 * Math.sin(t * 2.2 + 1.3))),
      attend: 1,
    };
  }

  if (mode === "listening") {
    const [drive, attention] = tuning.listen;
    const [attack, release] = tuning.voiceEnv;
    // The mic gets the SAME envelope as the outgoing voice. Two smoothing laws
    // for the two directions would make her answer a person and a speaker with
    // visibly different reflexes, which reads as two creatures.
    const heard = smoothers.env.step("mic", clamp01(state.micLevel), dt, attack, release);
    return {
      ...SILENT_DRIVE,
      ax: clamp01(drive * heard),
      ay: clamp01(drive * heard * 0.6),
      // Attention rises on ANY live microphone, not only on a loud one: she is
      // attending because you are there, and a person who has gone quiet
      // mid-sentence has not stopped being spoken to.
      attend: clamp01(attention * (0.55 + 0.45 * heard)),
    };
  }

  if (mode === "working" || mode === "thinking" || mode === "error") {
    return pulseDrive(tuning, t);
  }

  return SILENT_DRIVE;
}
