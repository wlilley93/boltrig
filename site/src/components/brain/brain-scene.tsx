"use client";

import { useEffect, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { AdditiveBlending, Vector2, type Group, type ShaderMaterial } from "three";

import { type BrainConfig } from "./config";
import { hexToVec3 } from "./lib/sampling";
import { AMBIENT_FRAGMENT, AMBIENT_VERTEX, BRAIN_FRAGMENT, BRAIN_VERTEX } from "./lib/shaders";
import { makeStorySample, sampleStory } from "./story/story-keyframes";
import { useStory } from "./story/use-story";
import { useBrainResources } from "./use-brain-resources";
import { useBrainControls } from "./use-brain-controls";

const APPEAR_DURATION = 3.0; // seconds
// Reveal: the brain flies in *from the camera* (starts large/near the viewer) and
// settles back to its resting depth while unwinding one full horizontal turn.
const REVEAL_START_Z = 3.6; // near the opening camera (z≈5.4), not clipping its near plane
const REVEAL_SPIN = Math.PI * 2; // one full 360° rotation about Y, unwound into place

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
const clampUnit = (v: number) => Math.max(-1, Math.min(1, v));

/**
 * The brain particle system: an area-sampled point cloud of the model plus a
 * drifting ambient cloud. The brain holds a *fixed* orientation in the scene —
 * the viewer orbits it with `OrbitControls` (see `BrainCanvas`). This component
 * drives the reveal — the assembled brain **flies in from near the camera and
 * unwinds one full 360° horizontal turn** into its resting depth/orientation
 * (easeOutQuart) — plus live time/resolution/alpha uniforms on the R3F loop, and
 * pushes the user-editable colour/size/motion params from the controls store into
 * the shader uniforms imperatively (on store change, not per frame) so the panel
 * never re-renders the WebGL tree. The highlight/explode uniforms stay neutral in
 * this static view except for the scroll-driven finale dispersal (ADR-0013/0014).
 */
export const BrainScene = () => {
  const { brainGeometry, ambientGeometry, brainUniforms, ambientUniforms } =
    useBrainResources();

  const groupRef = useRef<Group>(null);
  const brainMatRef = useRef<ShaderMaterial>(null);
  const ambientMatRef = useRef<ShaderMaterial>(null);
  const appearStart = useRef<number | null>(null);
  // Last config object applied to the uniforms — identity check so the live sync
  // only runs when the controls store actually changes (no per-frame colour work).
  const lastConfig = useRef<BrainConfig | null>(null);
  // Reusable scroll-story sample (region focus + finale dispersal), mutated each
  // frame — no per-frame allocation.
  const storySample = useRef(makeStorySample());
  // Cursor halo: latest pointer position in NDC + whether the pointer is present.
  const pointerNDC = useRef(new Vector2(-10, -10));
  const cursorTarget = useRef(0);
  // Damped cursor-parallax rotation, kept in refs so the reveal spin can be added
  // on top each frame without the two writers fighting over `group.rotation`.
  const parallaxRY = useRef(0);
  const parallaxRX = useRef(0);

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      pointerNDC.current.set(
        (e.clientX / window.innerWidth) * 2 - 1,
        -((e.clientY / window.innerHeight) * 2 - 1),
      );
      cursorTarget.current = 1;
    };
    const onLeave = () => {
      cursorTarget.current = 0;
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerout", onLeave);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerout", onLeave);
    };
  }, []);

  useFrame((state) => {
    const t = state.clock.elapsedTime;
    const resY = state.size.height * state.viewport.dpr;
    const brainU = brainMatRef.current?.uniforms;
    const ambientU = ambientMatRef.current?.uniforms;

    // Push live, user-editable params into the uniforms when the store changes.
    // Done in the loop (not a useEffect) so the only writer to the material refs
    // is useFrame — the react-hooks immutability rule forbids mixing the two.
    const config = useBrainControls.getState().config;
    if (config !== lastConfig.current) {
      lastConfig.current = config;
      if (brainU) {
        brainU.uCool.value.copy(hexToVec3(config.brainCool));
        brainU.uWarm.value.copy(hexToVec3(config.brainWarm));
        brainU.uEdgeColor.value.copy(hexToVec3(config.edgeColor));
        brainU.uCenterColor.value.copy(hexToVec3(config.centerColor));
        brainU.uCenterRadius.value = config.centerRadius;
        brainU.uCenterFalloff.value = config.centerFalloff;
        brainU.uSynapse.value.copy(hexToVec3(config.synapseColor));
        brainU.uSize.value = config.particleSize;
        brainU.uSynapseRate.value = config.synapseRate;
        brainU.uFlowSpeed.value = config.flowSpeed;
        brainU.uFlowAmount.value = config.flowAmount;
        brainU.uGlow.value = config.glowStrength;
        brainU.uDeepColor.value.copy(hexToVec3(config.deepColor));
        brainU.uOcclusionStrength.value = config.occlusionStrength;
        brainU.uCursorColor.value.copy(hexToVec3(config.cursorColor));
        brainU.uCursorStrength.value = config.cursorStrength;
      }
      if (ambientU) {
        ambientU.uColor.value.copy(hexToVec3(config.ambientColor));
        ambientU.uSize.value = config.ambientSize;
        ambientU.uSpeed.value = config.ambientSpeed;
        ambientU.uRange.value = config.ambientRange;
      }
    }

    // Entrance reveal — held until the loader hands off (`entered`), so the
    // immersive assemble-in plays *after* the loader fades, not behind it.
    const entered = useStory.getState().entered;
    if (entered && appearStart.current === null) appearStart.current = t;
    const p =
      appearStart.current === null
        ? 0
        : Math.min(1, (t - appearStart.current) / APPEAR_DURATION);
    const eased = 1 - Math.pow(1 - p, 4); // easeOutQuart — smooth settle

    // Scroll-story focus: drive the (otherwise-neutral) region-highlight and
    // finale-explode uniforms from the narrative progress, so each chapter scans
    // a region and the last chapter disperses the brain. Read imperatively so
    // scrolling never re-renders this tree.
    const story = sampleStory(useStory.getState().progress, storySample.current);

    // Live render uniforms (clock + resolution + reveal alpha).
    if (brainU) {
      brainU.iTime.value = t;
      brainU.iResolutionY.value = resY;
      brainU.iAlpha.value = eased;
      brainU.uHighlightPos.value.copy(story.region);
      brainU.uHighlightStrength.value = story.highlight;
      // Only the scroll-driven finale disperses the brain now — the entrance keeps
      // the brain fully assembled and flies it in instead (see group block below).
      brainU.uExplode.value = story.explode;
      // Cursor halo: trail the pointer (eased) and fade the effect in/out. Shrink
      // the NDC radius as the camera pulls away (so the halo stays small relative
      // to the brain when it's far, not a screen-filling blob).
      brainU.uMouse.value.lerp(pointerNDC.current, config.cursorFollow);
      brainU.uAspect.value = state.size.width / Math.max(1, state.size.height);
      brainU.uCursor.value += (cursorTarget.current - brainU.uCursor.value) * config.cursorFade;
      const camDist = state.camera.position.length(); // brain is centred at origin
      // Halo radius scales with the configured base, shrinking as the camera pulls
      // away (clamped to 0.4×..1.3× the base so it never vanishes or fills the screen).
      const cr = config.cursorRadius;
      brainU.uCursorRadius.value = Math.min(cr * 1.3, Math.max(cr * 0.4, (cr * 4.6) / camDist));
    }
    if (ambientU) {
      ambientU.iTime.value = t;
      ambientU.iResolutionY.value = resY;
      ambientU.iAlpha.value = eased;
    }

    const group = groupRef.current;
    if (group) {
      // Reveal: fly in from near the camera back to the resting depth.
      group.position.z = lerp(REVEAL_START_Z, 0, eased);
      // Subtle cursor parallax — the brain tilts a touch toward the pointer
      // (scaled by the eased cursor strength, so it's still until you move).
      const k = (brainU ? brainU.uCursor.value : 0) * config.cursorParallax;
      const targetRY = clampUnit(pointerNDC.current.x) * 0.12 * k;
      const targetRX = -clampUnit(pointerNDC.current.y) * 0.07 * k;
      parallaxRY.current += (targetRY - parallaxRY.current) * 0.04;
      parallaxRX.current += (targetRX - parallaxRX.current) * 0.04;
      // Reveal: one full 360° horizontal turn that unwinds to the resting
      // orientation as the brain settles in, with parallax layered on top.
      const revealSpin = (1 - eased) * REVEAL_SPIN;
      group.rotation.y = parallaxRY.current + revealSpin;
      group.rotation.x = parallaxRX.current;
    }
  });

  return (
    <group ref={groupRef} position={[0, 0, REVEAL_START_Z]}>
      <points frustumCulled={false}>
        <primitive object={brainGeometry} attach="geometry" />
        <shaderMaterial
          ref={brainMatRef}
          uniforms={brainUniforms}
          vertexShader={BRAIN_VERTEX}
          fragmentShader={BRAIN_FRAGMENT}
          transparent
          depthWrite={false}
          blending={AdditiveBlending}
        />
      </points>

      <points frustumCulled={false}>
        <primitive object={ambientGeometry} attach="geometry" />
        <shaderMaterial
          ref={ambientMatRef}
          uniforms={ambientUniforms}
          vertexShader={AMBIENT_VERTEX}
          fragmentShader={AMBIENT_FRAGMENT}
          transparent
          depthWrite={false}
          blending={AdditiveBlending}
        />
      </points>
    </group>
  );
};
