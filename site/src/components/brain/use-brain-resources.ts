import { useMemo } from "react";
import { BufferAttribute, BufferGeometry, Vector2, Vector3, type IUniform } from "three";
import { useGLTF } from "@react-three/drei";

import { BRAIN_CONFIG } from "./config";
import {
  centerAndScale,
  computeOcclusion,
  gatherTriangles,
  hexToVec3,
  makeAmbientBuffers,
  makeSeeds,
  sampleSurface,
} from "./lib/sampling";
import { useBrainControls } from "./use-brain-controls";

type Uniforms = Record<string, IUniform>;

export interface BrainResources {
  brainGeometry: BufferGeometry;
  ambientGeometry: BufferGeometry;
  brainUniforms: Uniforms;
  ambientUniforms: Uniforms;
}

/**
 * Loads the brain model, samples its surface into a point cloud, and builds the
 * geometries + shader uniform sets for both the brain and the ambient cloud.
 *
 * Geometry rebuilds only when the count / occlusion controls change (subscribed
 * by selector, so the control panel commits those on release). Uniform objects
 * are built **once** from `BRAIN_CONFIG` defaults — their live values are pushed
 * in imperatively by `BrainScene` from the controls store, so colour/size/motion
 * tweaks never rebuild geometry or re-render the WebGL tree.
 */
export function useBrainResources(): BrainResources {
  const { scene: model } = useGLTF(BRAIN_CONFIG.modelUrl);
  const surfaceCount = useBrainControls((s) => s.config.surfaceCount);
  const ambientCount = useBrainControls((s) => s.config.ambientCount);
  const occlusionRadius = useBrainControls((s) => s.config.occlusionRadius);

  const brainGeometry = useMemo(() => {
    const tris = gatherTriangles(model);
    const { positions, normals } = sampleSurface(tris, Math.max(100, surfaceCount));
    centerAndScale(positions, 1.45);
    const occlusion = computeOcclusion(positions, occlusionRadius);
    const geom = new BufferGeometry();
    geom.setAttribute("position", new BufferAttribute(positions, 3));
    geom.setAttribute("aNormal", new BufferAttribute(normals, 3));
    geom.setAttribute("aSeed", new BufferAttribute(makeSeeds(positions.length / 3), 1));
    geom.setAttribute("aOcclusion", new BufferAttribute(occlusion, 1));
    return geom;
  }, [model, surfaceCount, occlusionRadius]);

  const ambientGeometry = useMemo(() => {
    const { positions, dirs, seeds } = makeAmbientBuffers(Math.max(0, ambientCount));
    const geom = new BufferGeometry();
    geom.setAttribute("position", new BufferAttribute(positions, 3));
    geom.setAttribute("aDir", new BufferAttribute(dirs, 3));
    geom.setAttribute("aSeed", new BufferAttribute(seeds, 1));
    return geom;
  }, [ambientCount]);

  const brainUniforms = useMemo<Uniforms>(
    () => ({
      iTime: { value: 0 },
      iAlpha: { value: 0 },
      iResolutionY: { value: 720 },
      uCool: { value: hexToVec3(BRAIN_CONFIG.brainCool) },
      uWarm: { value: hexToVec3(BRAIN_CONFIG.brainWarm) },
      uEdgeColor: { value: hexToVec3(BRAIN_CONFIG.edgeColor) },
      uCenterColor: { value: hexToVec3(BRAIN_CONFIG.centerColor) },
      uCenterRadius: { value: BRAIN_CONFIG.centerRadius },
      uCenterFalloff: { value: BRAIN_CONFIG.centerFalloff },
      uSynapse: { value: hexToVec3(BRAIN_CONFIG.synapseColor) },
      uSize: { value: BRAIN_CONFIG.particleSize },
      uSynapseRate: { value: BRAIN_CONFIG.synapseRate },
      uFlowSpeed: { value: BRAIN_CONFIG.flowSpeed },
      uFlowAmount: { value: BRAIN_CONFIG.flowAmount },
      uGlow: { value: BRAIN_CONFIG.glowStrength },
      uDepthDarkness: { value: BRAIN_CONFIG.depthDarkness },
      uDeepColor: { value: hexToVec3(BRAIN_CONFIG.deepColor) },
      uOcclusionStrength: { value: BRAIN_CONFIG.occlusionStrength },
      uHighlightColor: { value: hexToVec3(BRAIN_CONFIG.highlightColor) },
      uHighlightPos: { value: new Vector3(0, 0, 0) },
      uHighlightRadius: { value: BRAIN_CONFIG.highlightRadius },
      uHighlightStrength: { value: 0 },
      uFocusFadeStrength: { value: BRAIN_CONFIG.focusFadeStrength },
      uIsolateStrength: { value: BRAIN_CONFIG.isolateStrength },
      uExplode: { value: 0 },
      uExplodeDist: { value: BRAIN_CONFIG.explodeDistance },
      // Cursor halo (driven by BrainScene from pointer events). Starts off-screen.
      uMouse: { value: new Vector2(-10, -10) },
      uCursor: { value: 0 },
      uAspect: { value: 1 },
      uCursorRadius: { value: BRAIN_CONFIG.cursorRadius },
      uCursorColor: { value: hexToVec3(BRAIN_CONFIG.cursorColor) },
      uCursorStrength: { value: BRAIN_CONFIG.cursorStrength },
    }),
    [],
  );

  const ambientUniforms = useMemo<Uniforms>(
    () => ({
      iTime: { value: 0 },
      iAlpha: { value: 0 },
      iResolutionY: { value: 720 },
      uColor: { value: hexToVec3(BRAIN_CONFIG.ambientColor) },
      uSize: { value: BRAIN_CONFIG.ambientSize },
      uSpeed: { value: BRAIN_CONFIG.ambientSpeed },
      uRange: { value: BRAIN_CONFIG.ambientRange },
    }),
    [],
  );

  return { brainGeometry, ambientGeometry, brainUniforms, ambientUniforms };
}

// Warm the loader cache as soon as this module is imported.
useGLTF.preload(BRAIN_CONFIG.modelUrl);
