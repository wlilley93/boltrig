// The self-trigger mitigations: two candidate answers to the one defect that
// blocks shipping client-side barge-in, behind a switch, with NEITHER chosen.
//
// The defect (measured 2026-08-13, docs/BARGEIN-2026-08-13.md): with the user
// silent and only the companion's AEC residual in the microphone, the energy
// gate fires 0.3-1.0s into her turn once the residual passes about -50 dBFS
// (0/6 trials at -52, 5/6 at -50, 6/6 at -48 and above). A *stationary* residual
// at the same RMS never fires, even at -30 dBFS. So the gate is not mistuned; it
// is a speech detector working correctly on the wrong voice. Retuning a
// threshold cannot fix that, and the fast-down/slow-up floor tracker actively
// makes it worse: the floor sinks into the gaps between her words and her next
// syllable reads as an onset above it.
//
// Both mitigations below therefore stop guessing and use the reference signal
// the page already has - the playback bus analyser, which carries exactly what
// the webview is about to emit and nothing else:
//
//   reference-margin   The bar the microphone must clear rises with her own
//                      playback level, so her leakage cannot clear it however
//                      modulated it is. Latency is untouched: the gate still
//                      fires on the first three hot frames.
//   playback-hangover  The gate is blocked outright while her own audio is
//                      audible, plus a trailing window, and fires in the gaps
//                      between her words. Immune by construction; costs latency.
//
// `echo-floor` is the third setting and the default: today's behaviour, with
// neither mitigation active. It is the measured-broken one. It stays the default
// because choosing between the other two needs a measurement of the operator's
// real room at their real speaker volume, and silently retuning against a room
// nobody heard is the mistake the plan warns about. See the doc's "Choosing
// between them" for the procedure that settles it.

/** Which self-trigger mitigation is active. `echo-floor` is neither. */
export type BargeInSelfTriggerMode =
  | "echo-floor"
  | "reference-margin"
  | "playback-hangover";

export const BARGE_IN_SELF_TRIGGER_MODES: readonly BargeInSelfTriggerMode[] = [
  "echo-floor",
  "reference-margin",
  "playback-hangover",
];

/** Unchanged behaviour. Deliberately not a mitigation: see the file header. */
export const BARGE_IN_DEFAULT_SELF_TRIGGER_MODE: BargeInSelfTriggerMode = "echo-floor";

export interface SelfTriggerTuning {
  mode: BargeInSelfTriggerMode;
  /**
   * Echo coupling: how far below the playback bus the companion's residual
   * arrives at the microphone, in dB, negative. This is NOT AEC3's ERLE alone -
   * it folds in speaker volume, room, microphone sensitivity and AGC, which is
   * why it is a measurement rather than a constant. -20dB is a deliberately
   * pessimistic placeholder (a -20 dBFS playback bus leaving -40 dBFS in the
   * microphone, inside the band that self-triggers today).
   */
  couplingDb: number;
  /** How far above that expected residual a frame must sit to count as the
   * user. 6dB doubles the amplitude; the user's own voice arrives uncancelled,
   * tens of dB above the residual, so this is not a tight squeeze. */
  marginDb: number;
  /**
   * Peak-hold release on the reference envelope, dB per second. Fast attack,
   * slow release: the whole point is that the bar must NOT sink into the gaps
   * between her words the way the floor tracker does. 24dB/s falls 2.4dB across
   * a 100ms inter-word gap and 12dB across half a second of real silence.
   */
  releaseDbPerSecond: number;
  /** playback-hangover only: how long after her audio goes quiet the gate stays
   * blocked. Covers speaker-to-microphone flight time, AEC3's own processing
   * delay and room decay - and is the latency this mode costs. */
  hangoverMs: number;
  /** playback-hangover only: the playback-bus level above which her audio counts
   * as audible at all, dBFS. Below it there is nothing to leak. */
  hangoverReferenceDb: number;
}

export const BARGE_IN_SELF_TRIGGER_DEFAULTS: SelfTriggerTuning = {
  mode: BARGE_IN_DEFAULT_SELF_TRIGGER_MODE,
  couplingDb: -20,
  marginDb: 6,
  releaseDbPerSecond: 24,
  hangoverMs: 80,
  hangoverReferenceDb: -45,
};

export interface SelfTriggerObservation {
  /** RMS of the playback bus this frame, 0..1 - what the webview is emitting. */
  reference: number;
  /** True while the companion's audio is queued or playing. */
  playing: boolean;
  /** Frame spacing in milliseconds, so release and hangover are in real time. */
  frameMs: number;
}

export interface SelfTriggerVerdict {
  /** An additional amplitude the frame must clear, 0 when the mode adds none. */
  bar: number;
  /** True when the gate may not fire this frame at all. */
  blocked: boolean;
  /** The peak-held playback envelope, exposed for tests and instrumentation. */
  envelope: number;
}

export interface SelfTriggerGuard {
  observe(observation: SelfTriggerObservation): SelfTriggerVerdict;
  reset(): void;
  readonly tuning: SelfTriggerTuning;
}

export function amplitudeFromDb(decibels: number): number {
  return 10 ** (decibels / 20);
}

const IDLE: SelfTriggerVerdict = { bar: 0, blocked: false, envelope: 0 };

/**
 * Peak-hold the playback bus and answer, per frame, what the microphone has to
 * clear and whether the gate may fire at all.
 *
 * Stateful and single-call-per-frame: `observe` advances the envelope and the
 * hangover countdown, so the barge-in gate must call it exactly once per frame,
 * including frames it then ignores.
 */
export function createSelfTriggerGuard(
  tuning: SelfTriggerTuning = BARGE_IN_SELF_TRIGGER_DEFAULTS,
): SelfTriggerGuard {
  let envelope = 0;
  let hangoverFrames = 0;

  const advance = ({ reference, frameMs }: SelfTriggerObservation): void => {
    const level = Number.isFinite(reference) && reference > 0 ? reference : 0;
    const decay = amplitudeFromDb(-tuning.releaseDbPerSecond * (frameMs / 1_000));
    envelope = level >= envelope ? level : Math.max(level, envelope * decay);
    const audible = level >= amplitudeFromDb(tuning.hangoverReferenceDb);
    const budget = Math.max(1, Math.round(tuning.hangoverMs / Math.max(1, frameMs)));
    hangoverFrames = audible ? budget : Math.max(0, hangoverFrames - 1);
  };

  return {
    tuning,
    observe(observation) {
      if (!observation.playing) {
        envelope = 0;
        hangoverFrames = 0;
        return IDLE;
      }
      advance(observation);
      if (tuning.mode === "reference-margin") {
        return {
          bar: envelope * amplitudeFromDb(tuning.couplingDb + tuning.marginDb),
          blocked: false,
          envelope,
        };
      }
      if (tuning.mode === "playback-hangover") {
        return { bar: 0, blocked: hangoverFrames > 0, envelope };
      }
      return { bar: 0, blocked: false, envelope };
    },
    reset() {
      envelope = 0;
      hangoverFrames = 0;
    },
  };
}

/**
 * Where the switch lives.
 *
 * `localStorage` first, then the build-time environment, then the default - so
 * the operator can A/B the two mitigations in their own room from the devtools
 * console without a rebuild, which is the only way the measurement in the doc is
 * practical to run. A value that is not one of the three modes, or not a finite
 * number, is ignored rather than guessed at.
 *
 *   localStorage.setItem("boltrig.bargeIn.mode", "reference-margin")
 *   VITE_BARGE_IN_SELF_TRIGGER_MODE=playback-hangover
 */
export function resolveSelfTriggerTuning(): SelfTriggerTuning {
  const defaults = BARGE_IN_SELF_TRIGGER_DEFAULTS;
  return {
    mode: resolveMode(defaults.mode),
    couplingDb: resolveNumber("couplingDb", "ECHO_COUPLING_DB", defaults.couplingDb),
    marginDb: resolveNumber("marginDb", "REFERENCE_MARGIN_DB", defaults.marginDb),
    releaseDbPerSecond: resolveNumber(
      "releaseDbPerSecond",
      "REFERENCE_RELEASE_DB_PER_S",
      defaults.releaseDbPerSecond,
    ),
    hangoverMs: resolveNumber("hangoverMs", "HANGOVER_MS", defaults.hangoverMs),
    hangoverReferenceDb: resolveNumber(
      "hangoverReferenceDb",
      "HANGOVER_REFERENCE_DB",
      defaults.hangoverReferenceDb,
    ),
  };
}

/**
 * Whether the gate should publish a per-frame diagnostic event.
 *
 * Off unless asked for, and asked for the same way the mode is:
 *
 *   localStorage.setItem("boltrig.bargeIn.diagnostics", "1")
 *
 * This is what makes the real-room measurement in docs/BARGEIN-2026-08-13.md
 * runnable at all: the echo coupling can only be read from the two levels the
 * gate already has in front of it - the microphone and the playback bus - and
 * nothing else in the app can see either.
 */
export function resolveSelfTriggerDiagnostics(): boolean {
  const raw = override("diagnostics", "DIAGNOSTICS").toLowerCase();
  return raw === "1" || raw === "true" || raw === "on";
}

function resolveMode(fallback: BargeInSelfTriggerMode): BargeInSelfTriggerMode {
  const raw = override("mode", "SELF_TRIGGER_MODE");
  const match = BARGE_IN_SELF_TRIGGER_MODES.find((mode) => mode === raw);
  return match ?? fallback;
}

function resolveNumber(storageKey: string, envKey: string, fallback: number): number {
  const raw = override(storageKey, envKey);
  if (!raw) return fallback;
  const value = Number(raw);
  return Number.isFinite(value) ? value : fallback;
}

function override(storageKey: string, envKey: string): string {
  return readStorage(`boltrig.bargeIn.${storageKey}`) || readEnv(`VITE_BARGE_IN_${envKey}`);
}

function readStorage(key: string): string {
  try {
    return (globalThis.localStorage?.getItem(key) ?? "").trim();
  } catch {
    // A webview with storage disabled falls back to the build-time value.
    return "";
  }
}

function readEnv(key: string): string {
  const env = import.meta.env as Record<string, unknown> | undefined;
  const value = env?.[key];
  return typeof value === "string" ? value.trim() : "";
}
