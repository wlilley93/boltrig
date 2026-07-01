import { create } from "zustand";

/**
 * Global scroll-narrative state for the Brain Story. A single 0→1 `progress`
 * value (driven from Lenis by `StoryScrollDriver`) and the derived active
 * `section` index.
 *
 * Read **imperatively** (`useStory.getState()`) inside the R3F render loop — the
 * camera rig and the scene's uniform sync consume `progress` every frame without
 * subscribing, so scrolling never re-renders the heavy WebGL tree (mirrors how
 * `useBrainControls` is read in `BrainScene` / `BrainRenderer`). DOM chrome that
 * *should* re-render per section (telemetry focus, the section rail) subscribes
 * to `section` by selector instead.
 */
export interface StoryState {
  /** Whole-page scroll progress, 0 at the top → 1 at the bottom. */
  progress: number;
  /** Active chapter index (0-based), derived from `progress`. */
  section: number;
  /** Flips true when the loader hands off — gates the brain's entrance reveal. */
  entered: boolean;
  setProgress: (progress: number) => void;
  setSection: (section: number) => void;
  setEntered: (entered: boolean) => void;
}

export const useStory = create<StoryState>((set) => ({
  progress: 0,
  section: 0,
  entered: false,
  setProgress: (progress) => set({ progress }),
  setSection: (section) =>
    set((state) => (state.section === section ? state : { section })),
  setEntered: (entered) => set((state) => (state.entered === entered ? state : { entered })),
}));
