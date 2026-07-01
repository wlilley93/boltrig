import { Vector3 } from "three";

/**
 * Camera + focus keyframes for the scroll narrative — one per chapter, indexed
 * to match `STORY_SECTIONS` in `src/data/story.ts`. The whole-page scroll
 * progress (0→1) is mapped across these keyframes; `sampleStory` interpolates a
 * smooth state between adjacent frames, consumed by:
 *   - `BrainCameraRig` — damps the camera toward `position` / `target`.
 *   - `BrainScene` — pushes `region` / `highlight` / `explode` into the
 *     already-wired (but otherwise neutral) shader uniforms.
 *
 * Coordinate notes: the brain is centred at the origin, scaled to ~1.45 radius;
 * +z faces the viewer (front of the brain), +x is screen-right. A `target` with
 * a **negative** x looks left of the brain centre, so the brain renders on the
 * **right** of the frame (its resting "stand to the side" pose).
 */
export interface StoryKeyframe {
  /** Camera world position. */
  position: [number, number, number];
  /** Point the camera looks at (offset from origin frames the brain off-centre). */
  target: [number, number, number];
  /** Brain-local anchor of the region this chapter scans. */
  region: [number, number, number];
  /** How strongly that region is highlighted/isolated (0 = none, 1 = full focus). */
  highlight: number;
  /** Finale dispersal amount (0 = intact, 1 = fully blown out). */
  explode: number;
}

export const STORY_KEYFRAMES: StoryKeyframe[] = [
  // 0 — Arrival: wide, brain standing to the right, calm.
  { position: [0, 0.25, 5.4], target: [-0.95, 0, 0], region: [0, 0, 1], highlight: 0, explode: 0 },
  // 1 — The Cortex: push in toward the upper-front surface, scan it.
  { position: [1.7, 0.7, 3.5], target: [0.2, 0.45, 0.2], region: [0.0, 0.55, 0.95], highlight: 1, explode: 0 },
  // 2 — Signals (takeover): neutral framing; the full-screen overlay hides the brain.
  { position: [0, 0, 4.6], target: [0, 0, 0], region: [0, 0, 1], highlight: 0, explode: 0 },
  // 3 — The Network (temporal): swing out to the left flank, scan the side.
  { position: [-3.3, -0.2, 1.9], target: [-0.15, -0.05, 0.1], region: [-0.7, -0.1, 0.35], highlight: 1, explode: 0 },
  // 4 — Vision (occipital): orbit fully behind the brain, scan the rear.
  { position: [0.25, 0.45, -4.5], target: [0, 0.1, -0.5], region: [0.0, 0.05, -1.05], highlight: 1, explode: 0 },
  // 5 — Balance (cerebellum): drop low behind, scan the rear-underside.
  { position: [-0.5, -1.7, -3.8], target: [0, -0.35, -0.4], region: [0.0, -0.55, -0.75], highlight: 1, explode: 0 },
  // 6 — The Whole (finale): don't retreat to the front — keep sweeping the orbit
  //     (up and around to the rear-right, continuing the prior motion) while the
  //     brain blows outward. The centred CTA finale sits over the dispersed field.
  { position: [2.4, 0.7, -2.4], target: [0, 0.05, -0.2], region: [0, 0, 0], highlight: 0, explode: 1 },
];

/** Reusable, mutation-friendly result of `sampleStory` — avoids per-frame GC. */
export interface StorySample {
  position: Vector3;
  target: Vector3;
  region: Vector3;
  highlight: number;
  explode: number;
}

/** Create a fresh sample object for a consumer to reuse across frames. */
export const makeStorySample = (): StorySample => ({
  position: new Vector3(),
  target: new Vector3(),
  region: new Vector3(),
  highlight: 0,
  explode: 0,
});

/**
 * Interpolate the story state at a given scroll `progress` (0→1) into `dst`
 * (mutated in place, returned for convenience). Progress is spread evenly across
 * the keyframes: `progress = i/(n-1)` lands exactly on keyframe `i`, the spans
 * between blend linearly. Smoothing/easing is the consumer's job (the rig damps;
 * the scene reads the raw blend, which the camera motion already softens).
 */
export function sampleStory(progress: number, dst: StorySample): StorySample {
  const frames = STORY_KEYFRAMES;
  const last = frames.length - 1;
  const scaled = Math.min(Math.max(progress, 0), 1) * last;
  const i = Math.min(Math.floor(scaled), last - 1);
  const t = scaled - i;
  const a = frames[i];
  const b = frames[i + 1];

  dst.position.set(...a.position).lerp(_tmp.set(...b.position), t);
  dst.target.set(...a.target).lerp(_tmp.set(...b.target), t);
  dst.region.set(...a.region).lerp(_tmp.set(...b.region), t);
  dst.highlight = a.highlight + (b.highlight - a.highlight) * t;
  dst.explode = a.explode + (b.explode - a.explode) * t;
  return dst;
}

// Module-level scratch vector — `sampleStory` runs every frame, so it must not
// allocate. Single-threaded JS makes this reuse safe within one synchronous call.
const _tmp = new Vector3();
