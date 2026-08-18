/**
 * The bodies' tuning, which now lives one file per body.
 *
 * It was one 466-line module against the worker's 400-line floor, and that floor
 * cannot be waived: the structure gate re-loads its baseline from Git and
 * refuses a NEW debt entry, so the file had to shrink rather than be pinned.
 *
 * The original header argued for keeping a body's numbers side by side, because
 * the defect in both bodies was a RATIO between values that sat eighty lines
 * apart. That argument is about one body's numbers; each half still holds its
 * whole interface and its whole shipped struct together, and the shared ramp
 * vocabulary is in ./bodyRamp.ts. This barrel keeps every importer untouched.
 */
export {
  pulsedCore,
  ramp,
  type EnergyRamp,
  type LimbMix,
} from "./bodyRamp";
export { JARVIS_TUNING, type JarvisTuning } from "./jarvisTuning";
export { ULTRON_TUNING, type UltronTuning } from "./ultronTuning";
