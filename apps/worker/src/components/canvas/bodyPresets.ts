/**
 * The per-mode presets for each body, re-exported from one place.
 *
 * Jarvis and Ultron were one 485-line file until the Worker structural floor
 * (400 physical lines, NFR-MNT-07) refused it. Splitting by CHARACTER rather
 * than by kind - all of Jarvis here, all of Ultron there - keeps a body's
 * arrival, modes and pulses readable together, which is how they are tuned.
 *
 * This barrel stays so no call site had to move for the split.
 */
export {
  JARVIS_ARRIVAL,
  JARVIS_MODES,
  JARVIS_PULSES,
  jarvisModeTuning,
} from "./jarvisPresets";
export {
  ULTRON_ARRIVAL,
  ULTRON_MODES,
  ULTRON_PULSES,
  ultronModeTuning,
} from "./ultronPresets";
