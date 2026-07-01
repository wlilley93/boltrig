"use client";

import { Suspense, useEffect } from "react";
import { Canvas } from "@react-three/fiber";

import { BrainCameraRig } from "./brain-camera-rig";
import { BrainRenderer } from "./brain-renderer";
import { BrainScene } from "./brain-scene";
import { STORY_KEYFRAMES } from "./story/story-keyframes";
import { useBrainControls } from "./use-brain-controls";

/** Reduced particle budget for phones / low-memory devices (desktop untouched). */
const MOBILE_SURFACE_COUNT = 60000;
const MOBILE_AMBIENT_COUNT = 2200;

const isLowPowerDevice = () => {
  const nav = navigator as Navigator & { deviceMemory?: number };
  return (
    window.matchMedia("(max-width: 767px)").matches ||
    (nav.deviceMemory !== undefined && nav.deviceMemory <= 4)
  );
};

/**
 * On small/low-memory devices, shrink the geometry budgets in the controls store
 * before the GLB resolves (surface sampling only runs after the model loads, so
 * the cheap counts apply to the first build). An effect, not render-time config,
 * so SSR/hydration and desktop defaults are untouched.
 */
function useMobileQualityScale() {
  useEffect(() => {
    if (!isLowPowerDevice()) return;
    const { setParam } = useBrainControls.getState();
    setParam("surfaceCount", MOBILE_SURFACE_COUNT);
    setParam("ambientCount", MOBILE_AMBIENT_COUNT);
  }, []);
}

export interface BrainCanvasProps {
  /** Accessible label for the decorative WebGL region. */
  label?: string;
  className?: string;
}

/**
 * Client leaf hosting the WebGL particle brain. Full-bleed and fixed behind the
 * page content. The viewer no longer orbits it — the scroll-driven
 * `BrainCameraRig` flies the camera between story keyframes, so the brain stands
 * to one side at rest and the narrative camera moves around it. The `<canvas>`
 * itself is decorative — meaningful page copy and the `<h1>` live in the
 * surrounding view.
 */
export const BrainCanvas = ({
  label = "Animated particle brain",
  className,
}: BrainCanvasProps) => {
  useMobileQualityScale();
  return (
    <Canvas
      className={className}
      aria-label={label}
      role="img"
      dpr={[1, 2]}
      gl={{ antialias: true }}
      camera={{ fov: 45, near: 0.1, far: 80, position: STORY_KEYFRAMES[0].position }}
    >
      <color attach="background" args={["#01040e"]} />
      <fog attach="fog" args={["#01040e", 0, 18]} />
      <Suspense fallback={null}>
        <BrainScene />
      </Suspense>
      <BrainCameraRig />
      <BrainRenderer />
    </Canvas>
  );
};
