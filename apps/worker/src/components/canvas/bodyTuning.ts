/**
 * The numbers that decide how a particle body LOOKS, re-exported from one place.
 *
 * One 466-line file until the Worker structural floor (400 physical lines,
 * NFR-MNT-07) refused it. The split follows the same seam as bodyPresets: the
 * shared ramp convention and its two evaluators in ./tuningScalars, then all of
 * Jarvis and all of Ultron in a file each. tests/visual/shader-bench.html still
 * has ONE struct per body to override, which is the property the original
 * header called load-bearing.
 *
 * This barrel stays so no call site had to move for the split.
 */
export {
  pulsedCore,
  ramp,
  type EnergyRamp,
  type LimbMix,
} from "./tuningScalars";
export { JARVIS_TUNING, type JarvisTuning } from "./jarvisTuning";
export { ULTRON_TUNING, type UltronTuning } from "./ultronTuning";
