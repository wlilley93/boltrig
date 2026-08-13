// Client-side barge-in: the cheap half of "the user started talking".
//
// Three measured facts shape everything here.
//
// 1. The transcript is NOT the trigger. Kyutai streaming STT emits its first
//    `speech_start` 1.746s into a clip whose speech begins ~0.3s in, because it
//    waits for a decoded token. A companion talking over you for 1.7s is not
//    barge-in. Detecting that *someone is talking* costs a few tens of
//    milliseconds and needs no words at all, so that question goes on the
//    critical path and the transcript follows behind it.
// 2. Interrupting is a PLAYBACK problem, not a generation one. TTS runs at
//    ~10-11x realtime, so an 11s utterance is fully synthesised in under a
//    second: by the time a human could interrupt there is nothing left to
//    cancel. The mechanism is stopping the speaker and dropping what is already
//    queued. A self-hosted `POST /interrupt` only bites past ~10s of audio; it
//    is free, so we send it, but it is not the mechanism.
// 3. Echo cancellation decides the architecture. Capture runs through
//    `getUserMedia({echoCancellation, noiseSuppression, autoGainControl})`,
//    which gives WebRTC AEC3 for headphones AND open speakers - but AEC3 can
//    only cancel audio the webview itself played. TTS playback therefore stays
//    in the page audio graph (see VoiceCall's `playPcm`). If playback ever
//    moves to the Rust side the canceller loses its reference, the microphone
//    hears the companion, and she interrupts herself in a loop.
//
// The gate below is a pure state machine so the thresholds can be tested
// without an AudioContext.
//
// One defect remains open and is measured in docs/BARGEIN-2026-08-13.md: on a
// speech-shaped AEC residual above about -50 dBFS the companion interrupts
// herself. The two candidate mitigations live in ./voiceSelfTrigger behind a
// switch whose default is today's behaviour - see that file's header for why
// neither is chosen here.

import {
  BARGE_IN_SELF_TRIGGER_DEFAULTS,
  amplitudeFromDb,
  createSelfTriggerGuard,
  type SelfTriggerGuard,
} from "./voiceSelfTrigger";

/** 10ms frames: an AnalyserNode with fftSize 512 spans 10.67ms at 48kHz. */
export const BARGE_IN_FRAME_MS = 10;

/**
 * Consecutive above-threshold frames before the gate trips - 30ms of sustained
 * energy. Measured on real speech onsets (two barge-in captures, 10ms frames):
 * the first voiced frame already sits +35.0dB and +39.1dB above the preceding
 * 150ms floor, and stays there. Three frames therefore costs ~20ms and buys
 * rejection of single-frame transients (a key click, a mouse button, a door).
 */
export const BARGE_IN_TRIGGER_FRAMES = 3;

/**
 * How far above the tracked floor a frame must sit to count as speech.
 *
 * Measured rather than picked: on those same captures the +12dB crossing
 * happened in the same 10ms frame as the +20dB crossing once, and one frame
 * *earlier* the other time, while speech itself ran +35dB. So 12dB is the
 * earliest crossing available and still leaves ~23dB of headroom over the
 * quietest real onset. Anything lower buys no latency and only loses margin.
 */
export const BARGE_IN_MARGIN_DB = 12;

/**
 * The self-trigger guard. While the companion is playing, the floor tracker is
 * following AEC3's *residual* echo rather than the room, so the same 12dB
 * margin would be measured against a higher baseline. Requiring 18dB over that
 * residual keeps the gate deaf to leakage while the user's own voice - which
 * arrives at the microphone uncancelled, tens of dB above the residual - still
 * trips it.
 */
export const BARGE_IN_ECHO_MARGIN_DB = 18;

/**
 * Absolute floor, -48 dBFS. The relative test alone fires on nothing in a
 * digitally silent room: one real capture had a -89 dBFS floor, where +12dB is
 * still -77 dBFS. Anchored to measurement - inter-word floors in the real
 * captures ran -59 to -61 dBFS and voiced speech ran -26 dBFS median, so this
 * sits comfortably between the two and gates out neither.
 */
export const BARGE_IN_MIN_RMS = 0.004;

/** 500ms of frames before the gate may fire, so a cold floor cannot trip it. */
export const BARGE_IN_WARMUP_FRAMES = 50;

/**
 * The other half of the self-trigger guard: 200ms at the start of each spoken
 * turn during which the echo floor tracks fast in both directions and the gate
 * cannot fire at all.
 *
 * Without it the guard has a hole. The echo floor has to be seeded from
 * somewhere when playback starts; seeding it from the first playing frame lets
 * a user who talks over the very first syllable seed it with their own voice
 * and go undetected, while seeding it from the room floor lets an unusually
 * loud speaker's residual trip the gate before the tracker catches up. Refusing
 * to fire while it catches up closes both, and costs nothing a person would
 * notice - nobody decides to interrupt inside the first 200ms of a sentence.
 */
export const BARGE_IN_PLAYBACK_SETTLE_FRAMES = 20;

/** One interrupt per utterance, not one per syllable. */
export const BARGE_IN_COOLDOWN_MS = 400;

/**
 * After a local barge-in the socket keeps delivering the turn the provider has
 * not stopped generating yet, so inbound PCM is dropped rather than queued for
 * this long. Refreshed while the user is still talking, and hard-capped by
 * BARGE_IN_SUPPRESS_MAX_MS so a provider that never confirms cannot mute the
 * companion indefinitely.
 */
export const BARGE_IN_SUPPRESS_MS = 600;
export const BARGE_IN_SUPPRESS_MAX_MS = 2_500;

export interface BargeInObservation {
  /** Root-mean-square amplitude of this frame, 0..1. */
  rms: number;
  /** True while the companion's audio is queued or playing. */
  playing: boolean;
  /** Milliseconds, for cooldown only. */
  now: number;
  /**
   * RMS of the playback bus this frame, 0..1: the companion's own signal, read
   * from the playback analyser. Absent (or 0) leaves the self-trigger guard with
   * no reference, which is what `echo-floor` mode assumes anyway.
   */
  reference?: number;
}

export interface BargeInVerdict {
  /** The edge: this frame completed a run long enough to interrupt. */
  trigger: boolean;
  /** This frame was above threshold, trigger or not. */
  active: boolean;
}

export interface BargeInGate {
  observe(observation: BargeInObservation): BargeInVerdict;
  /** Floors and run length only; call after a deliberate audio-path change. */
  reset(): void;
}

interface BargeInGateOptions {
  triggerFrames?: number;
  marginDb?: number;
  echoMarginDb?: number;
  minRms?: number;
  warmupFrames?: number;
  cooldownMs?: number;
  settleFrames?: number;
  /** The self-trigger mitigation. Defaults to `echo-floor`, which adds nothing. */
  selfTrigger?: SelfTriggerGuard;
}

/**
 * Fast down, slow up: the floor chases quiet within ~50ms and rises over ~2s,
 * so it settles into room noise without ever climbing into speech.
 *
 * `active` freezes the up branch. A rising floor is only ever ambient; letting
 * a sustained utterance raise it would make the gate deaf to exactly the thing
 * it is listening for, part-way through the sentence being spoken over it.
 */
function nextFloor(floor: number, rms: number, active: boolean): number {
  if (rms < floor) return floor * 0.7 + rms * 0.3;
  return active ? floor : floor * 0.995 + rms * 0.005;
}

function sanitise(rms: number): number {
  return Number.isFinite(rms) && rms > 0 ? rms : 0;
}

interface GateState {
  /** Room noise, tracked only while the companion is silent. */
  quietFloor: number | null;
  /** AEC residual, tracked only while she is speaking. */
  echoFloor: number | null;
  observedFrames: number;
  hotFrames: number;
  settling: number;
  wasPlaying: boolean;
  lastTriggerAt: number;
}

const QUIET_GATE_STATE: GateState = {
  quietFloor: null,
  echoFloor: null,
  observedFrames: 0,
  hotFrames: 0,
  settling: 0,
  wasPlaying: false,
  lastTriggerAt: Number.NEGATIVE_INFINITY,
};

function floorOf(state: GateState, playing: boolean): number | null {
  return playing ? state.echoFloor : state.quietFloor;
}

function setFloor(state: GateState, playing: boolean, value: number): void {
  if (playing) state.echoFloor = value;
  else state.quietFloor = value;
}

/** The threshold this frame has to clear, in the same units as the sample. */
function thresholdFor(
  state: GateState,
  tracked: number,
  playing: boolean,
  limits: { marginDb: number; echoMarginDb: number; minRms: number },
): number {
  // During playback the residual echo is the thing to clear, but the room is
  // still the lower bound on what "quiet" means.
  const floor = playing ? Math.max(tracked, state.quietFloor ?? 0) : tracked;
  const margin = amplitudeFromDb(playing ? limits.echoMarginDb : limits.marginDb);
  return Math.max(limits.minRms, floor * margin);
}

/** A turn has started: seed the echo tracker from the room rather than from
 * this frame, and let it settle before the gate can fire. */
function beginTurn(state: GateState, settleFrames: number): void {
  state.echoFloor = state.quietFloor;
  state.settling = settleFrames;
  state.hotFrames = 0;
}

interface ArmingLimits {
  playing: boolean;
  blocked: boolean;
  now: number;
  warmupFrames: number;
  cooldownMs: number;
  triggerFrames: number;
}

/** Everything except "is this frame hot" that has to hold before interrupting. */
function isArmed(state: GateState, limits: ArmingLimits): boolean {
  return limits.playing
    && !limits.blocked
    && state.observedFrames >= limits.warmupFrames
    && limits.now - state.lastTriggerAt >= limits.cooldownMs
    && state.hotFrames >= limits.triggerFrames;
}

/** Fast in both directions while settling: whatever the speaker leaks past
 * AEC3 at the start of a turn is what the tracker has to land on. */
function settleEcho(state: GateState, sample: number): void {
  state.settling -= 1;
  state.echoFloor = state.echoFloor === null
    ? sample
    : state.echoFloor * 0.7 + sample * 0.3;
}

/**
 * Energy gate over ~10ms frames. Floors are tracked separately for silence and
 * for playback, because the second one is measuring AEC residual rather than
 * the room, and only the playback one decides an interrupt.
 */
export function createBargeInGate(options: BargeInGateOptions = {}): BargeInGate {
  const triggerFrames = options.triggerFrames ?? BARGE_IN_TRIGGER_FRAMES;
  const warmupFrames = options.warmupFrames ?? BARGE_IN_WARMUP_FRAMES;
  const cooldownMs = options.cooldownMs ?? BARGE_IN_COOLDOWN_MS;
  const settleFrames = options.settleFrames ?? BARGE_IN_PLAYBACK_SETTLE_FRAMES;
  const limits = {
    marginDb: options.marginDb ?? BARGE_IN_MARGIN_DB,
    echoMarginDb: options.echoMarginDb ?? BARGE_IN_ECHO_MARGIN_DB,
    minRms: options.minRms ?? BARGE_IN_MIN_RMS,
  };
  const selfTrigger = options.selfTrigger
    ?? createSelfTriggerGuard(BARGE_IN_SELF_TRIGGER_DEFAULTS);
  const state: GateState = { ...QUIET_GATE_STATE };
  const quiet = { trigger: false, active: false } as const;

  return {
    observe({ rms, playing, now, reference }) {
      const sample = sanitise(rms);
      state.observedFrames += 1;
      if (playing && !state.wasPlaying) beginTurn(state, settleFrames);
      state.wasPlaying = playing;
      // Once per frame, including frames returning early: the guard's envelope
      // and hangover are time-based and must not skip.
      const guard = selfTrigger.observe({
        reference: sanitise(reference ?? 0),
        playing,
        frameMs: BARGE_IN_FRAME_MS,
      });
      if (playing && state.settling > 0) {
        settleEcho(state, sample);
        return quiet;
      }

      const tracked = floorOf(state, playing);
      if (tracked === null) {
        setFloor(state, playing, sample);
        return quiet;
      }

      const bar = Math.max(thresholdFor(state, tracked, playing, limits), guard.bar);
      const active = sample >= bar;
      setFloor(state, playing, nextFloor(tracked, sample, active));
      // A blocked frame breaks the run rather than pausing it: the three frames
      // that interrupt her have to be three frames the guard allowed.
      state.hotFrames = active && !guard.blocked ? state.hotFrames + 1 : 0;

      const armed = isArmed(state, {
        playing,
        blocked: guard.blocked,
        now,
        warmupFrames,
        cooldownMs,
        triggerFrames,
      });
      if (!armed) return { trigger: false, active };
      state.lastTriggerAt = now;
      state.hotFrames = 0;
      return { trigger: true, active };
    },
    reset() {
      Object.assign(state, QUIET_GATE_STATE);
      selfTrigger.reset();
    },
  };
}

/** Root-mean-square of one time-domain frame. */
export function frameRms(samples: ArrayLike<number>): number {
  const length = samples.length;
  if (!length) return 0;
  let total = 0;
  for (let index = 0; index < length; index += 1) {
    const sample = samples[index] ?? 0;
    total += sample * sample;
  }
  return Math.sqrt(total / length);
}
