/**
 * The two bodies' presets, which now live one file per body.
 *
 * They were one 485-line module against the worker's 400-line floor, and that
 * floor cannot be waived here: the structure gate re-loads its baseline from Git
 * and refuses a NEW debt entry outright, so the file had to shrink rather than
 * be pinned. The seam is the one the module already drew down its middle.
 *
 * This barrel stays so that every importer is untouched and the split reads as
 * the move it is.
 */
export {
  FAMILIAR_ARRIVAL,
  FAMILIAR_MODES,
  familiarModeTuning,
} from "./familiarPresets";
export {
  JARVIS_ARRIVAL,
  JARVIS_MODES,
  JARVIS_PULSES,
  JARVIS_SPEECH,
  JARVIS1_TUNING,
  jarvisModeTuning,
  jarvis1ModeTuning,
  type Jarvis1Tuning,
} from "./jarvisPresets";
export {
  ULTRON_ARRIVAL,
  ULTRON_MODES,
  ULTRON_PULSES,
  ultronModeTuning,
} from "./ultronPresets";
