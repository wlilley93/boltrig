"use client";

import { useEffect, useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { Vector2 } from "three";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { ShaderPass } from "three/examples/jsm/postprocessing/ShaderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { GammaCorrectionShader } from "three/examples/jsm/shaders/GammaCorrectionShader.js";

import { BRAIN_CONFIG } from "./config";
import { hexToVec3 } from "./lib/sampling";
import { FINAL_FRAGMENT, FINAL_VERTEX } from "./lib/shaders";
import { useBrainControls } from "./use-brain-controls";

/**
 * Drives the real-bloom + warped-gradient composite. Takes over rendering from
 * R3F (via a positive-priority `useFrame`) and runs a deliberately flat,
 * temporally-stable pipeline:
 *   1. `sceneComposer` — render the brain once, then a single `UnrealBloomPass`
 *      (everything is on the default layer, so no per-frame layer switching).
 *   2. `finalComposer` — a full-screen shader compositing that scene+bloom over
 *      the warped corner-gradient background.
 *
 * The earlier three-composer / layer-mask pipeline flickered because two of the
 * composers rendered empty layers and the camera layer mask was rewritten every
 * frame; collapsing to one scene render + one bloom removes that instability
 * while keeping a genuine UnrealBloom. Corner colours are live from the store.
 */
export const BrainRenderer = () => {
  const gl = useThree((s) => s.gl);
  const scene = useThree((s) => s.scene);
  const camera = useThree((s) => s.camera);
  const size = useThree((s) => s.size);

  const pipeline = useMemo(() => {
    const resolution = new Vector2(size.width, size.height);

    const sceneComposer = new EffectComposer(gl);
    sceneComposer.renderToScreen = false;
    sceneComposer.addPass(new RenderPass(scene, camera));
    sceneComposer.addPass(new ShaderPass(GammaCorrectionShader));
    // Real UnrealBloom, applied once to the whole brain. Seeded from config; the
    // three params are then live-synced from the store each frame (see useFrame).
    const bloomPass = new UnrealBloomPass(
      resolution,
      BRAIN_CONFIG.bloomStrength,
      BRAIN_CONFIG.bloomRadius,
      BRAIN_CONFIG.bloomThreshold,
    );
    sceneComposer.addPass(bloomPass);

    const finalPass = new ShaderPass({
      uniforms: {
        iTime: { value: 0 },
        tScene: { value: null },
        iCornerBlue: { value: hexToVec3(BRAIN_CONFIG.cornerBlue) },
        iCornerOrange: { value: hexToVec3(BRAIN_CONFIG.cornerOrange) },
      },
      vertexShader: FINAL_VERTEX,
      fragmentShader: FINAL_FRAGMENT,
    });

    const finalComposer = new EffectComposer(gl);
    finalComposer.addPass(finalPass);

    return { sceneComposer, finalComposer, finalPass, bloomPass };
  }, [gl, scene, camera, size.width, size.height]);

  // Mirror the memoised pipeline into a ref so the render loop can mutate the
  // composers' uniforms (forbidden directly on a hook/useMemo return value).
  const pipelineRef = useRef(pipeline);
  useEffect(() => {
    pipelineRef.current = pipeline;
  }, [pipeline]);

  // Keep both composers sized to the canvas.
  useEffect(() => {
    const dpr = gl.getPixelRatio();
    for (const composer of [pipeline.sceneComposer, pipeline.finalComposer]) {
      composer.setPixelRatio(dpr);
      composer.setSize(size.width, size.height);
    }
  }, [pipeline, gl, size.width, size.height]);

  useEffect(() => {
    return () => {
      pipeline.sceneComposer.dispose();
      pipeline.finalComposer.dispose();
    };
  }, [pipeline]);

  // Last corner colours pushed to the composite — identity check so the live
  // sync only runs when the store changes (kept in the loop, not a useEffect, so
  // useFrame stays the sole writer of the pipeline's uniforms — immutability rule).
  const lastCorners = useRef<{ blue: string; orange: string } | null>(null);

  // Positive priority → R3F hands the render loop to us.
  useFrame((state) => {
    const p = pipelineRef.current;

    const { cornerBlue, cornerOrange, bloomStrength, bloomRadius, bloomThreshold } =
      useBrainControls.getState().config;
    if (lastCorners.current?.blue !== cornerBlue || lastCorners.current?.orange !== cornerOrange) {
      lastCorners.current = { blue: cornerBlue, orange: cornerOrange };
      p.finalPass.uniforms.iCornerBlue.value.copy(hexToVec3(cornerBlue));
      p.finalPass.uniforms.iCornerOrange.value.copy(hexToVec3(cornerOrange));
    }

    // Live-sync bloom — these are plain props on the pass, safe to assign each
    // frame (the pass reads them at render time, no rebuild needed).
    p.bloomPass.strength = bloomStrength;
    p.bloomPass.radius = bloomRadius;
    p.bloomPass.threshold = bloomThreshold;

    p.finalPass.uniforms.iTime.value = state.clock.elapsedTime;
    p.sceneComposer.render();
    p.finalPass.uniforms.tScene.value = p.sceneComposer.readBuffer.texture;
    p.finalComposer.render();
  }, 1);

  return null;
};
