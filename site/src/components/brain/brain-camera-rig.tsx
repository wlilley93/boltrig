"use client";

import { useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { Vector3 } from "three";

import { makeStorySample, sampleStory } from "./story/story-keyframes";
import { useStory } from "./story/use-story";

// Damping rate — higher = the camera catches up to the scroll target faster.
// Frame-rate independent (see `MathUtils.damp`), so it feels identical at any FPS.
const DAMP = 3.2;

const prefersReducedMotion = () =>
  typeof window !== "undefined" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * The scroll-driven camera — replaces `OrbitControls`. Every frame it samples the
 * story keyframes at the current scroll `progress` (read imperatively from
 * `useStory`, so scrolling never re-renders this tree) and **damps** the camera
 * position + look-at target toward that sample. The damping turns the discrete
 * per-section keyframes into one continuous, weighty flythrough.
 *
 * Runs at default `useFrame` priority — i.e. before `BrainRenderer` (priority 1)
 * takes over rendering — exactly where `BrainOrbit` used to update the camera.
 * Under `prefers-reduced-motion` it holds the opening framing (keyframe 0).
 */
export const BrainCameraRig = () => {
  const camera = useThree((s) => s.camera);

  // Sampled story target (mutated each frame) + the camera's live look-at point
  // (damped separately from position so both ease smoothly).
  const sample = useRef(makeStorySample());
  const lookAt = useRef(new Vector3());
  const initialised = useRef(false);
  const reduced = useRef(prefersReducedMotion());

  useFrame((state, delta) => {
    const progress = reduced.current ? 0 : useStory.getState().progress;
    const s = sampleStory(progress, sample.current);

    // Responsive framing: on narrow/portrait viewports (tablet/phone), centre the
    // brain (drop the lateral offset) and pull the camera back so it isn't cropped
    // or shoved off-screen by the side-framed keyframes.
    const aspect = state.size.width / Math.max(1, state.size.height);
    const mobile = Math.max(0, Math.min(1, (1.1 - aspect) / 0.6));
    if (mobile > 0) {
      s.target.x *= 1 - 0.85 * mobile;
      s.target.y *= 1 - 0.4 * mobile;
      s.position.multiplyScalar(1 + 0.4 * mobile);
    }

    if (!initialised.current) {
      // Snap to the first framing on mount so there is no fly-in from the
      // canvas's default camera position.
      initialised.current = true;
      camera.position.copy(s.position);
      lookAt.current.copy(s.target);
      camera.lookAt(lookAt.current);
      return;
    }

    // Frame-rate-independent exponential damp toward the sampled framing.
    const k = 1 - Math.exp(-DAMP * Math.min(delta, 0.1));
    camera.position.lerp(s.position, k);
    lookAt.current.lerp(s.target, k);
    camera.lookAt(lookAt.current);
  });

  return null;
};
