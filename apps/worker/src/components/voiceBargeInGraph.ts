// Barge-in, Web Audio half: the capture-side analyser, the ~10ms poll that
// drives the gate, and what happens the moment it trips.
//
// The pure decision logic lives in ./voiceBargeIn so its thresholds can be
// tested without an AudioContext; this file is the wiring that feeds it and the
// side effects it causes.

import {
  BARGE_IN_FRAME_MS,
  BARGE_IN_SUPPRESS_MAX_MS,
  BARGE_IN_SUPPRESS_MS,
  createBargeInGate,
  frameRms,
  type BargeInGate,
} from "./voiceBargeIn";
import {
  createSelfTriggerGuard,
  resolveSelfTriggerDiagnostics,
  resolveSelfTriggerTuning,
  type SelfTriggerTuning,
} from "./voiceSelfTrigger";

/** One string for both triggers, so the surface reads the same whether the
 * local gate or the provider's own VAD stopped the audio. */
export const BARGE_IN_NOTICE = "Playback stopped while you were speaking.";

/** The slice of the call's media resources the gate reads and writes. */
export interface BargeInHost {
  playbackSources: Set<AudioBufferSourceNode>;
  micAnalyser?: AnalyserNode;
  micFrame?: Float32Array | null;
  /**
   * The playback bus analyser - the same node VoiceCall's `analyser` names, and
   * the reference signal for the self-trigger mitigations: every scheduled
   * source connects through it, so it carries the companion's audio and nothing
   * else. Absent means no reference, which only `echo-floor` mode tolerates.
   */
  analyser?: AnalyserNode;
  referenceFrame?: Float32Array | null;
  bargeInGate?: BargeInGate;
  bargeInTimer?: number | null;
  onBargeIn?: () => void;
  /**
   * 0..1 how loudly the person is talking, for whatever body is on the Stage.
   *
   * THROTTLED, NOT PER FRAME. The gate polls at 100Hz because that is what
   * catching a speech onset in 30ms costs; a React state update at 100Hz is a
   * different question entirely, and pushing one would spend the whole saving
   * the analyser was polled quickly to make. See MIC_LEVEL_PUBLISH_MS.
   */
  onMicLevel?: (level: number) => void;
  /** Epoch milliseconds of the last level published, and what it said. */
  micLevelAt?: number;
  micLevelLast?: number;
  /** Epoch milliseconds until which inbound assistant PCM is dropped, not
   * queued - the interrupted turn keeps arriving after the local flush. */
  suppressPlaybackUntil: number;
  /** Epoch milliseconds of the barge-in that opened that window. */
  bargeInAt: number;
}

/** 512 samples spans 10.67ms at 48kHz - one poll's worth, no more. */
const BARGE_IN_FFT_SIZE = 512;

/**
 * How often the level reaches the body, in milliseconds.
 *
 * ~30Hz, the same rate the outgoing voice's spectral features are sampled at,
 * so the two directions arrive on the same clock and a body cannot appear to
 * answer one of them more eagerly than the other. It is also comfortably below
 * a frame at 60fps: publishing faster than the renderer can draw only spends
 * CPU crossing from JS into React to be overwritten.
 */
const MIC_LEVEL_PUBLISH_MS = 33;

/** Below this, two levels are the same number as far as a body is concerned. */
const MIC_LEVEL_EPSILON = 0.01;

/** Publish if enough time has passed AND the value actually moved -- or if it
 *  has just reached silence, which is a change a body must never miss. */
function publishMicLevel(host: BargeInHost, level: number, now: number): void {
  if (!host.onMicLevel) return;
  const last = host.micLevelLast ?? 0;
  const silenced = level === 0 && last !== 0;
  if (!silenced && now - (host.micLevelAt ?? 0) < MIC_LEVEL_PUBLISH_MS) return;
  if (!silenced && Math.abs(level - last) < MIC_LEVEL_EPSILON) return;
  host.micLevelAt = now;
  host.micLevelLast = level;
  host.onMicLevel(level);
}

/**
 * Give the gate its own capture-side analyser.
 *
 * It hangs off the microphone source rather than the upload path, and rides the
 * existing gain-0 keep-alive to the destination so the graph pulls it without
 * ever making the microphone audible.
 */
export function attachBargeInCapture(
  context: AudioContext,
  source: AudioNode,
  keepAlive: AudioNode,
): AnalyserNode {
  const analyser = context.createAnalyser();
  analyser.fftSize = BARGE_IN_FFT_SIZE;
  analyser.smoothingTimeConstant = 0;
  source.connect(analyser);
  analyser.connect(keepAlive);
  return analyser;
}

/** The gate's share of a call's media resources, ready to spread into them.
 *
 * `onMicLevel` comes AFTER `tuning` rather than beside `onBargeIn`, where it
 * belongs by meaning, purely so the existing self-trigger test's three-argument
 * call keeps working. A caller wanting the meter and the shipped tuning passes
 * `undefined` for the middle one, which is the honest way to say "the default".
 */
export function bargeInHostFields(
  micAnalyser: AnalyserNode | null,
  onBargeIn: () => void,
  tuning: SelfTriggerTuning = resolveSelfTriggerTuning(),
  onMicLevel?: (level: number) => void,
): Omit<BargeInHost, "playbackSources" | "analyser"> {
  return {
    micAnalyser: micAnalyser ?? undefined,
    micFrame: null,
    referenceFrame: null,
    bargeInGate: createBargeInGate({ selfTrigger: createSelfTriggerGuard(tuning) }),
    bargeInTimer: null,
    onBargeIn,
    onMicLevel,
    suppressPlaybackUntil: 0,
    bargeInAt: 0,
  };
}

/**
 * RMS of the companion's own playback this frame.
 *
 * Read from the playback analyser rather than reconstructed from the queued
 * buffers: it is the signal actually reaching `destination`, which is the same
 * thing AEC3 gets as its reference. Zero when there is no analyser to read, so a
 * host without one behaves exactly as it did before.
 */
function referenceRms(host: BargeInHost): number {
  const analyser = host.analyser;
  if (!analyser || typeof analyser.getFloatTimeDomainData !== "function") return 0;
  const frame = host.referenceFrame?.length === analyser.fftSize
    ? host.referenceFrame
    : new Float32Array(analyser.fftSize);
  host.referenceFrame = frame;
  analyser.getFloatTimeDomainData(frame);
  return frameRms(frame);
}

/**
 * The per-frame diagnostic, off unless `boltrig.bargeIn.diagnostics` asks for
 * it. A DOM event rather than a log line: the operator's measurement script
 * needs the numbers, not a transcript of them, and nothing is emitted at all in
 * a normal call.
 *
 *   addEventListener("boltrig:barge-in-frame", (event) => rows.push(event.detail))
 */
export const BARGE_IN_DIAGNOSTIC_EVENT = "boltrig:barge-in-frame";

export interface BargeInFrameDiagnostic {
  /** Microphone RMS this frame, 0..1. */
  rms: number;
  /** Playback bus RMS this frame, 0..1 - the companion's own signal. */
  reference: number;
  playing: boolean;
  active: boolean;
  trigger: boolean;
  now: number;
}

function publishBargeInFrame(enabled: boolean, detail: BargeInFrameDiagnostic): void {
  if (!enabled || typeof CustomEvent !== "function") return;
  window.dispatchEvent(new CustomEvent(BARGE_IN_DIAGNOSTIC_EVENT, { detail }));
}

export function stopBargeInGate(host: BargeInHost): void {
  if (host.bargeInTimer != null) {
    window.clearInterval(host.bargeInTimer);
    host.bargeInTimer = null;
  }
}

/**
 * Poll the capture-side analyser every ~10ms and interrupt on sustained energy.
 *
 * Deliberately not hung off the upload path's `onaudioprocess`: that buffer is
 * 4096 frames, 85ms at 48kHz, so a gate quantised to it could not reach the
 * target however it was tuned. A 512-sample analyser polled at 10ms spans
 * 10.67ms per read, and three consecutive reads is 30ms of speech.
 */
export function startBargeInGate(host: BargeInHost, isMuted: () => boolean): void {
  if (host.bargeInTimer != null || !host.micAnalyser || !host.bargeInGate) return;
  const diagnostics = resolveSelfTriggerDiagnostics();
  host.bargeInTimer = window.setInterval(() => {
    const analyser = host.micAnalyser;
    const gate = host.bargeInGate;
    // A muted microphone carries no speech to detect, and observing its silence
    // would only drag the tracked floor down before the user unmutes.
    if (!analyser || !gate) return;
    if (isMuted()) {
      // A muted microphone is silence to look at as well as to listen to. Left
      // unpublished, the body would hold whatever it last heard and go on
      // attending to a person who has switched their microphone off.
      publishMicLevel(host, 0, Date.now());
      return;
    }
    if (typeof analyser.getFloatTimeDomainData !== "function") {
      // No time-domain read, no energy gate. Stop rather than poll forever;
      // the provider-side `interrupted` event still stops playback there.
      stopBargeInGate(host);
      return;
    }
    const frame = host.micFrame ?? new Float32Array(analyser.fftSize);
    host.micFrame = frame;
    analyser.getFloatTimeDomainData(frame);
    const now = Date.now();
    const rms = frameRms(frame);
    const reference = referenceRms(host);
    const playing = host.playbackSources.size > 0;
    const { trigger, active, level } = gate.observe({ rms, playing, now, reference });
    publishBargeInFrame(diagnostics, { rms, reference, playing, active, trigger, now });
    // While SHE is talking the microphone is carrying AEC residual, not a
    // person, and a level read off that would make her react to her own voice
    // through the listening channel as well as the speaking one.
    publishMicLevel(host, playing ? 0 : level, now);
    if (trigger) {
      host.bargeInAt = now;
      host.suppressPlaybackUntil = now + BARGE_IN_SUPPRESS_MS;
      host.onBargeIn?.();
      return;
    }
    // Hold the drop window open while the user is still talking over a turn the
    // provider has not stopped sending - but never past the cap, or a provider
    // that never confirms would mute the companion indefinitely.
    if (active && host.suppressPlaybackUntil > now) {
      host.suppressPlaybackUntil = Math.min(
        now + BARGE_IN_SUPPRESS_MS,
        host.bargeInAt + BARGE_IN_SUPPRESS_MAX_MS,
      );
    }
  }, BARGE_IN_FRAME_MS);
}
/**
 * Origin of a self-hosted TTS runtime that accepts `POST /interrupt`.
 *
 * Absent by default, and an unusable value is absent rather than guessed - the
 * Worker must never invent a local port to POST at. Set
 * `VITE_SELF_HOSTED_TTS_ORIGIN=http://127.0.0.1:8911` to point at pocket-voice.
 * A different origin also needs its own `connect-src` entry in
 * `src-tauri/tauri.conf.json`, or the Tauri webview refuses the request.
 */
export function configuredSelfHostedTtsOrigin(): string | null {
  const raw = (import.meta.env.VITE_SELF_HOSTED_TTS_ORIGIN ?? "").trim();
  if (!raw) return null;
  try {
    const parsed = new URL(raw);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
    if (parsed.username || parsed.password) return null;
    return parsed.origin;
  } catch {
    return null;
  }
}

/**
 * Best-effort upstream cancel, sent alongside the local flush and never
 * awaited by it. It only bites when generation still spans playback - past
 * ~10s of audio - so a refusal, a 404 or a blocked origin changes nothing the
 * user hears and is deliberately silent.
 */
export function requestSelfHostedInterrupt(): void {
  const origin = configuredSelfHostedTtsOrigin();
  if (!origin || typeof fetch !== "function") return;
  try {
    void fetch(`${origin}/interrupt`, { method: "POST" }).catch(() => {
      // Barge-in already succeeded locally; the upstream cancel is a bonus.
    });
  } catch {
    // Same: a throwing fetch must not break the interrupt that already worked.
  }
}
