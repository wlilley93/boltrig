import { create } from "zustand";

import { BRAIN_CONFIG, type BrainConfig } from "./config";

/** Live camera-control parameters (not scene shader content, so kept separate). */
export interface BrainCameraControls {
  autoRotate: boolean;
  autoRotateSpeed: number;
}

const DEFAULT_CAMERA: BrainCameraControls = {
  autoRotate: true,
  autoRotateSpeed: 0.45,
};

/**
 * Live, user-editable state for the particle-brain scene. `config` mirrors
 * `BRAIN_CONFIG` and is mutated through the control panel; the scene reads it
 * imperatively (via `getState`/`subscribe`) and pushes values into shader
 * uniforms, so dragging a slider never re-renders the WebGL tree. Geometry-
 * affecting params (counts, occlusion radius) DO re-render `useBrainResources`
 * by selector subscription, so the panel commits those on release.
 */
export interface BrainControlsState {
  config: BrainConfig;
  camera: BrainCameraControls;
  panelOpen: boolean;
  setParam: <K extends keyof BrainConfig>(key: K, value: BrainConfig[K]) => void;
  setCamera: <K extends keyof BrainCameraControls>(
    key: K,
    value: BrainCameraControls[K],
  ) => void;
  setPanelOpen: (open: boolean) => void;
  reset: () => void;
}

export const useBrainControls = create<BrainControlsState>((set) => ({
  config: { ...BRAIN_CONFIG },
  camera: { ...DEFAULT_CAMERA },
  panelOpen: false,
  setParam: (key, value) =>
    set((state) => ({ config: { ...state.config, [key]: value } })),
  setCamera: (key, value) =>
    set((state) => ({ camera: { ...state.camera, [key]: value } })),
  setPanelOpen: (panelOpen) => set({ panelOpen }),
  reset: () => set({ config: { ...BRAIN_CONFIG }, camera: { ...DEFAULT_CAMERA } }),
}));
