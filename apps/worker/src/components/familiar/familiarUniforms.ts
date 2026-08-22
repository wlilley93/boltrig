// WHAT THE SHADER IS TOLD, in one place.
//
// Separated from the renderer because they are different jobs, and the renderer
// said so before this was its own file: frame() decides WHETHER and WHEN to
// draw — reduced motion, a hidden tab, a lost context — and this decides what
// the shader is handed once that has been settled. It is also the half that
// changes when a tuning grows a dial, which is a different rhythm from the half
// that changes when WebGL does.
//
// Reading a missing uniform's location as null is deliberate throughout: a
// shader recompiled without one should draw without it, not throw on the next
// frame. That matters more here than usual because familiar.frag is VENDORED —
// it arrives from boltrig-familiar and this side must tolerate it losing a
// uniform between versions rather than going black.

import { FAMILIAR_TUNING, type FamiliarTuning } from "../canvas/familiarTuning";
import type { FamiliarDrive } from "./familiarDrive";
import { dayWarmth } from "./familiarDrive";
import type { Mood } from "./familiarMood";
import type { FamiliarMode, FamiliarPresentationMode } from "./FamiliarState";

export const UNIFORMS = [
  "iTime", "iResolution", "uAudio", "uBeat", "uMouse", "uDay",
  "uValence", "uArousal", "uIrritation", "uFatigue", "uAttention",
  "uSocial", "uBuoyancy", "uLuminosity", "uTension", "uGesture",
  "uGestureAmt", "uPresence", "uCentreDock", "uScaleDock", "uFitScale",
  "uGaze", "uWorldRes", "uOrigin", "uPxScale", "uFill", "uPortWide",
  "uHover", "uCompanion", "uAperture",
  "uGene",
] as const;

export type UniformName = (typeof UNIFORMS)[number];
export type UniformMap = Partial<Record<UniformName, WebGLUniformLocation | null>>;

/** How much larger the voice portrait is than the compact porthole, as a ratio
 *  of the tuned composition rather than as a second pair of absolute numbers —
 *  so moving the dial moves both presentations together, which is what "the
 *  same creature, closer" means. The ratios reproduce the measured pair
 *  (0.45 / 0.62) from the shipped compact one (0.34 / 0.50) exactly. */
const VOICE_DOCK = 0.45 / 0.34;
const VOICE_FIT = 0.62 / 0.50;

/** Voice owns a portrait, not the compact companion porthole used elsewhere. */
export function familiarCompositionForMode(
  mode: FamiliarPresentationMode,
  tuning: FamiliarTuning = FAMILIAR_TUNING,
): { fitScale: number; scaleDock: number } {
  const [scaleDock, fitScale] = tuning.composition;
  return mode === "voice"
    ? { scaleDock: scaleDock * VOICE_DOCK, fitScale: fitScale * VOICE_FIT }
    : { scaleDock, fitScale };
}

/** One frame's worth of derived values, handed over as a single argument. A bag
 *  rather than nine positional parameters: they are almost all numbers of the
 *  same type, so a transposed pair would compile and simply draw wrong. */
export interface FamiliarFrameShot {
  w: number;
  h: number;
  t: number;
  drive: FamiliarDrive;
  tuning: FamiliarTuning;
  mood: Mood;
  mode: FamiliarMode;
  presentation: FamiliarPresentationMode;
  gesture: { id: number; amt: number };
}

export function pushFamiliarUniforms(
  gl: WebGL2RenderingContext,
  u: UniformMap,
  shot: FamiliarFrameShot,
): void {
  const { w, h, t, drive, tuning, mood: m, gesture } = shot;
  const f = (name: UniformName, value: number) => gl.uniform1f(u[name] ?? null, value);
  f("iTime", t);
  gl.uniform2f(u.iResolution ?? null, w, h);
  gl.uniform2f(u.uWorldRes ?? null, w, h);
  f("uPxScale", 1);
  gl.uniform2f(u.uOrigin ?? null, 0, 0);

  // Companion recipe from boltrig-familiar-web: the orb renders through the
  // porthole path, with the aperture pinned open.
  //
  // FAMILIAR DOES NOT ARRIVE, SHE IS THERE. She used to be born out of a
  // black-hole aperture over 1400ms, inherited from the porthole path the
  // summoned companions use. 1 is fully open and the shader's own hole gate --
  // 4a(1-a) -- is zero there.
  f("uFill", 1);
  f("uCompanion", 1);
  f("uPresence", 0);
  f("uAperture", 1);
  gl.uniform2f(u.uCentreDock ?? null, 0, 0);
  const composition = familiarCompositionForMode(shot.presentation, tuning);
  f("uScaleDock", composition.scaleDock);
  f("uFitScale", composition.fitScale);

  gl.uniform2f(u.uMouse ?? null, 0.5, 0.5);
  // GAZE IS THE STATE SIGNAL. Where she is looking says more at porthole size
  // than any change of brightness can, so it is what carries listening: at 96
  // pixels across, "brighter" is not a state anybody reads and "watching you"
  // is. Autonomous still -- cursor tracking is a later, deliberate step.
  const [idleGaze, engagedGaze] = tuning.gaze;
  f("uGaze", idleGaze + (engagedGaze - idleGaze) * drive.attend);
  f("uDay", dayWarmth(tuning));

  const [workLift, speakLift] = tuning.arousalLift;
  f("uValence", m.valence);
  f("uArousal", Math.min(1, m.arousal + (shot.mode === "speaking" ? speakLift : workLift)));
  f("uIrritation", m.irritation);
  f("uFatigue", m.fatigue);
  // A live microphone may only RAISE attention, never lower what the wander
  // arrived at on its own — being spoken to is not a reason to be less awake.
  f("uAttention", Math.max(m.attention, drive.attend));
  f("uSocial", m.social);
  f("uBuoyancy", m.buoyancy);
  f("uLuminosity", m.luminosity);
  f("uTension", m.tension);

  f("uGesture", gesture.id);
  f("uGestureAmt", gesture.amt);
  gl.uniform4f(u.uAudio ?? null, drive.ax, drive.ay, drive.az, drive.aw);
  f("uBeat", drive.beat);
  f("uPortWide", 0);
  f("uHover", 0);
}
