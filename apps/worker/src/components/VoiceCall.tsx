import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { MutableRefObject } from "react";
import { createPortal } from "react-dom";
import type {
  CallCreateResponse,
  CallEvent,
  CallStatus,
  CallUsage,
  RealtimeCall,
  AgentCapabilityInfo,
} from "@wlilley93/boltrig-web-sdk";

import { configuredApiOrigin } from "../apiOrigin";
import { client } from "../client";
import { isDesktop } from "../desktop";
import { StageBody, useFamiliarBody, type StageTurnInput } from "./StageBody";
import { useCharacter } from "./characters";
import { useStagePhenotype } from "./chat/useStagePhenotype";
import { FamiliarBadge } from "./familiar/FamiliarBadge";
import {
  attachBargeInCapture, BARGE_IN_NOTICE, bargeInHostFields, requestSelfHostedInterrupt,
  startBargeInGate, stopBargeInGate, type BargeInHost,
} from "./voiceBargeInGraph";
import { audioTracks, createVoicePlaybackAnalyser, resamplePcm16, safeDisconnect } from "./voiceMedia";
import "./VoiceCall.css";

interface VoiceCallProps {
  onFamiliarActivity?(activity: {
    speaking: boolean;
    level: number;
    bands?: number[];
    centroid?: number;
    onset?: number;
  }): void;
  // True for the whole life of a call attempt (creating through held), not
  // just while audio is playing - the Stage takes centre stage for the call.
  onCallActive?(active: boolean): void;
  conversationId: string | null;
  conversationTitle?: string;
  modelProfileId?: string;
  onConversation(id: string): void;
  onError(message: string): void;
  /** Chat embeds the service behind the round composer call control. */
  embedded?: boolean;
  /** Call history/profile choices belong in settings when embedded. */
  showOptions?: boolean;
}

interface VoiceLine {
  id: string;
  speaker: "You" | "Boltrig";
  text: string;
  /** True when the line was typed mid-call rather than spoken. */
  typed?: boolean;
}

type IncomingCallEvent = Pick<CallEvent, "type" | "payload"> &
  Partial<Pick<CallEvent, "id" | "call_id" | "participant_id" | "created_at">>;

/** Barge-in (Phase 5) contributes a capture-side energy gate, separate from
 * the playback analyser below, whose only job is "the user started talking". */
interface MediaResources extends BargeInHost {
  socket: WebSocket;
  context: AudioContext;
  stream: MediaStream;
  processor: ScriptProcessorNode;
  source: MediaStreamAudioSourceNode;
  mute: GainNode;
  /** Familiar lift (ADR 0025): fires as assistant playback starts/stops. */
  onPlayback?: (speaking: boolean) => void;
  /** Voice embodiment (A4): playback routes through this analyser; a ~30Hz
   * sampler emits bounded spectral features only - PCM never leaves the graph. */
  analyser?: AnalyserNode;
  voiceTimer?: number | null;
  prevSpectrum?: Float32Array | null;
  onVoiceFeatures?: (features: VoiceFeatures) => void;
  readyTimeout: number | null;
  rejectReady: ((reason: Error) => void) | null;
}

interface ModalBackgroundSnapshot {
  element: HTMLElement;
  ariaHidden: string | null;
  inertAttribute: string | null;
  inertProperty: boolean | undefined;
}

const VOICE_READY_TIMEOUT_MS = 15_000;

export interface VoiceFeatures {
  speaking: boolean;
  level: number;
  bands: number[];
  centroid: number;
  onset: number;
}

const QUIET_VOICE_FEATURES: VoiceFeatures = {
  speaking: false,
  level: 0,
  bands: [0, 0, 0, 0, 0, 0, 0, 0],
  centroid: 0,
  onset: 0,
};

const RECOVERED_CALL_NOTICE = "A voice call from this conversation can be resumed.";

/** Bounded spectral features from the playback analyser: level, eight log
 * bands, centroid, onset (positive spectral flux). Numbers only, all 0..1. */
function sampleVoiceFeatures(
  analyser: AnalyserNode,
  prev: Float32Array | null,
): { features: Omit<VoiceFeatures, "speaking">; spectrum: Float32Array } {
  const bins = analyser.frequencyBinCount;
  const data = new Uint8Array(bins);
  analyser.getByteFrequencyData(data);
  const spectrum = new Float32Array(bins);
  let total = 0;
  let weighted = 0;
  let flux = 0;
  for (let index = 0; index < bins; index += 1) {
    const value = (data[index] ?? 0) / 255;
    spectrum[index] = value;
    total += value;
    weighted += value * index;
    const delta = value - (prev?.[index] ?? 0);
    if (delta > 0) flux += delta;
  }
  const bands: number[] = [];
  for (let band = 0; band < 8; band += 1) {
    // Logarithmic bands: each spans an octave of the bin range.
    const lo = Math.floor(bins * (2 ** band - 1) / 255);
    const hi = Math.max(lo + 1, Math.floor(bins * (2 ** (band + 1) - 1) / 255));
    let sum = 0;
    for (let index = lo; index < hi && index < bins; index += 1) sum += spectrum[index] ?? 0;
    bands.push(Math.min(1, sum / (hi - lo) * 1.6));
  }
  return {
    features: {
      level: Math.min(1, (total / bins) * 2.4),
      bands,
      centroid: total > 0 ? weighted / total / bins : 0,
      onset: Math.min(1, flux / 6),
    },
    spectrum,
  };
}

function stopVoiceSampler(media: MediaResources) {
  if (media.voiceTimer != null) {
    window.clearInterval(media.voiceTimer);
    media.voiceTimer = null;
  }
  media.prevSpectrum = null;
  media.onVoiceFeatures?.({ speaking: false, level: 0, bands: [0, 0, 0, 0, 0, 0, 0, 0], centroid: 0, onset: 0 });
}

function startVoiceSampler(media: MediaResources) {
  if (media.voiceTimer != null || !media.analyser) return;
  media.voiceTimer = window.setInterval(() => {
    const analyser = media.analyser;
    if (!analyser) return;
    if (media.playbackSources.size === 0) {
      stopVoiceSampler(media);
      return;
    }
    const { features, spectrum } = sampleVoiceFeatures(analyser, media.prevSpectrum ?? null);
    media.prevSpectrum = spectrum;
    media.onVoiceFeatures?.({ speaking: true, ...features });
  }, 33);
}

class VoiceConnectionError extends Error {
  constructor(
    message: string,
    readonly nextStatus: "failed" | "reconnecting" = "failed",
  ) {
    super(message);
    this.name = "VoiceConnectionError";
  }
}

class VoiceConnectionCancelledError extends Error {
  constructor() {
    super("Voice connection setup was cancelled.");
    this.name = "VoiceConnectionCancelledError";
  }
}

export function VoiceCall({
  conversationId,
  conversationTitle,
  modelProfileId,
  onConversation,
  onError,
  onFamiliarActivity,
  onCallActive,
  embedded = false,
  showOptions = true,
}: VoiceCallProps) {
  const [call, setCall] = useState<RealtimeCall | null>(null);
  const [status, setStatus] = useState<CallStatus | "idle">("idle");
  const [lines, setLines] = useState<VoiceLine[]>([]);
  const [usage, setUsage] = useState<CallUsage | null>(null);
  const [eventNotice, setEventNotice] = useState("");
  const [approvalCount, setApprovalCount] = useState(0);
  const [agentProfiles, setAgentProfiles] = useState<AgentCapabilityInfo[]>([]);
  const [agentProfileId, setAgentProfileId] = useState("");
  const [recovered, setRecovered] = useState(false);
  const [recentCalls, setRecentCalls] = useState<RealtimeCall[]>([]);
  const [muted, setMuted] = useState(false);
  const [textDraft, setTextDraft] = useState("");
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [dismissedNotice, setDismissedNotice] = useState("");
  const [focusedParticipantId, setFocusedParticipantId] = useState<string | null>(null);
  const [familiarActivity, setFamiliarActivity] = useState<VoiceFeatures>({
    ...QUIET_VOICE_FEATURES,
    bands: [...QUIET_VOICE_FEATURES.bands],
  });
  const mediaRef = useRef<MediaResources | null>(null);
  const callRef = useRef<RealtimeCall | null>(null);
  const textDraftOwnerRef = useRef<{
    conversationId: string | null;
    callId: string | null;
  } | null>(null);
  const readyRef = useRef(false);
  const endingRef = useRef(false);
  const mutedRef = useRef(false);
  const callStartedAtRef = useRef<number | null>(null);
  const connectionAttemptRef = useRef(0);
  const playAtRef = useRef(0);
  const callScreenRef = useRef<HTMLElement | null>(null);
  const endCallRef = useRef<() => Promise<void>>(async () => undefined);
  const modalOpenerRef = useRef<HTMLElement | null>(null);
  const onFamiliarActivityRef = useRef(onFamiliarActivity);
  onFamiliarActivityRef.current = onFamiliarActivity;
  const onCallActiveRef = useRef(onCallActive);
  onCallActiveRef.current = onCallActive;
  const inCall = status === "creating"
    || status === "joining"
    || status === "active"
    || status === "reconnecting"
    || status === "held";
  const selectedCharacterId = useFamiliarBody();
  const selectedCharacter = useCharacter(selectedCharacterId);
  const { phenotype: stagePhenotype } = useStagePhenotype(
    inCall && selectedCharacter.readsPhenotype,
  );

  useEffect(() => {
    onCallActiveRef.current?.(inCall);
  }, [inCall]);
  useEffect(() => () => onCallActiveRef.current?.(false), []);
  const seenEventIdsRef = useRef(new Set<string>());
  const pendingApprovalsRef = useRef(new Set<string>());

  useEffect(() => {
    setFocusedParticipantId(null);
  }, [call?.id]);

  const callScreenOpen = status !== "idle"
    && status !== "ended"
    && status !== "realtime_unavailable";

  useLayoutEffect(() => {
    if (!callScreenOpen || typeof document === "undefined") return;
    const dialog = callScreenRef.current;
    if (!dialog) return;

    const activeElement = document.activeElement;
    modalOpenerRef.current = activeElement instanceof HTMLElement
      && activeElement !== document.body
      && !dialog.contains(activeElement)
      ? activeElement
      : null;

    const background = new Map<HTMLElement, ModalBackgroundSnapshot>();
    const isDialogBranch = (element: HTMLElement) => (
      element === dialog || element.contains(dialog)
    );
    const makeBackgroundModal = (element: HTMLElement) => {
      if (isDialogBranch(element) || background.has(element)) return;
      background.set(element, {
        element,
        ariaHidden: element.getAttribute("aria-hidden"),
        inertAttribute: element.getAttribute("inert"),
        inertProperty: "inert" in element ? element.inert : undefined,
      });
      element.setAttribute("aria-hidden", "true");
      element.setAttribute("inert", "");
      if ("inert" in element) element.inert = true;
    };

    for (const child of document.body.children) {
      if (child instanceof HTMLElement) makeBackgroundModal(child);
    }

    const observer = new MutationObserver((records) => {
      for (const record of records) {
        for (const added of record.addedNodes) {
          if (added instanceof HTMLElement && added.parentElement === document.body) {
            makeBackgroundModal(added);
          }
        }
      }
    });
    observer.observe(document.body, { childList: true });

    const focusDialog = () => dialog.focus({ preventScroll: true });
    const focusFirstControl = () => {
      const first = modalFocusableElements(dialog)[0];
      if (first) first.focus({ preventScroll: true });
      else focusDialog();
    };
    const handleFocusIn = (event: FocusEvent) => {
      if (!(event.target instanceof Node) || dialog.contains(event.target)) return;
      focusFirstControl();
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (event.target instanceof HTMLInputElement) {
          // Escape while typing sheds the composer first; it must not hang up.
          event.target.blur();
          return;
        }
        event.preventDefault();
        event.stopPropagation();
        void endCallRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const controls = modalFocusableElements(dialog);
      if (controls.length === 0) {
        event.preventDefault();
        focusDialog();
        return;
      }
      const first = controls[0]!;
      const last = controls[controls.length - 1]!;
      const focused = document.activeElement;
      if (event.shiftKey && (focused === first || !dialog.contains(focused))) {
        event.preventDefault();
        last.focus({ preventScroll: true });
      } else if (!event.shiftKey && focused === last) {
        event.preventDefault();
        first.focus({ preventScroll: true });
      }
    };

    document.addEventListener("focusin", handleFocusIn, true);
    document.addEventListener("keydown", handleKeyDown, true);
    focusDialog();

    return () => {
      observer.disconnect();
      document.removeEventListener("focusin", handleFocusIn, true);
      document.removeEventListener("keydown", handleKeyDown, true);
      for (const snapshot of background.values()) {
        restoreAttribute(snapshot.element, "aria-hidden", snapshot.ariaHidden);
        if (snapshot.inertProperty !== undefined && "inert" in snapshot.element) {
          snapshot.element.inert = snapshot.inertProperty;
        }
        restoreAttribute(snapshot.element, "inert", snapshot.inertAttribute);
      }
      const opener = modalOpenerRef.current;
      modalOpenerRef.current = null;
      if (opener?.isConnected) opener.focus({ preventScroll: true });
    };
  }, [callScreenOpen]);

  useEffect(() => {
    if (!callScreenOpen) return;
    const recorded = call?.status === "ended" ? null : callStartMilliseconds(call);
    if (recorded !== null) callStartedAtRef.current = recorded;
    if (callStartedAtRef.current === null) callStartedAtRef.current = Date.now();
    const update = () => setElapsedSeconds(Math.max(
      0,
      Math.floor((Date.now() - (callStartedAtRef.current ?? Date.now())) / 1_000),
    ));
    update();
    const timer = window.setInterval(update, 1_000);
    return () => window.clearInterval(timer);
  }, [call?.created_at, call?.id, call?.started_at, callScreenOpen]);

  // A non-urgent freezone notice clears itself after the same quiet interval as
  // the decided target. Approval notices are sticky because dismissing a card
  // must never imply that the underlying request was answered.
  useEffect(() => {
    setDismissedNotice("");
    if (!eventNotice || approvalCount > 0) return;
    const pinVisualRecoveryNotice =
      document.documentElement.dataset.visualPinRecoveredCallNotice === "true"
      && eventNotice === RECOVERED_CALL_NOTICE;
    if (pinVisualRecoveryNotice) return;
    const timer = window.setTimeout(() => setDismissedNotice(eventNotice), 9_800);
    return () => window.clearTimeout(timer);
  }, [approvalCount, eventNotice]);

  useEffect(() => () => {
    connectionAttemptRef.current += 1;
    closeMedia(mediaRef, readyRef, playAtRef);
  }, []);

  useEffect(() => {
    if (typeof client.capabilities !== "function") return;
    void client.capabilities().then((result) => {
      setAgentProfiles(result.agent_capabilities ?? []);
    }).catch(() => setAgentProfiles([]));
  }, []);

  useEffect(() => {
    let cancelled = false;
    if (typeof client.calls !== "function") return () => { cancelled = true; };
    void client.calls(10).then((result) => {
      if (!cancelled) setRecentCalls(result.calls);
    }).catch(() => {
      // Recent calls are supplementary to the live voice controls.
    });
    return () => { cancelled = true; };
  }, [conversationId]);

  useEffect(() => {
    let cancelled = false;
    if (
      conversationId
      && callRef.current?.conversation_id === conversationId
    ) {
      return () => { cancelled = true; };
    }
    const attempt = ++connectionAttemptRef.current;
    closeMedia(mediaRef, readyRef, playAtRef);
    textDraftOwnerRef.current = null;
    setTextDraft("");
    callRef.current = null;
    setCall(null);
    setStatus("idle");
    setRecovered(false);
    mutedRef.current = false;
    setMuted(false);
    callStartedAtRef.current = null;
    setElapsedSeconds(0);
    setFamiliarActivity({ ...QUIET_VOICE_FEATURES, bands: [...QUIET_VOICE_FEATURES.bands] });
    setLines([]);
    setUsage(null);
    setEventNotice("");
    setApprovalCount(0);
    seenEventIdsRef.current.clear();
    pendingApprovalsRef.current.clear();
    if (!conversationId) return () => { cancelled = true; };
    if (typeof client.currentCall !== "function") {
      return () => { cancelled = true; };
    }
    void client.currentCall(conversationId).then(async (result) => {
      if (
        cancelled
        || connectionAttemptRef.current !== attempt
        || !result.call
      ) return;
      textDraftOwnerRef.current = null;
      setTextDraft("");
      setCall(result.call);
      callRef.current = result.call;
      setStatus("reconnecting");
      setRecovered(true);
      setEventNotice(RECOVERED_CALL_NOTICE);
      await restoreCallHistory(result.call.id, attempt);
    }).catch(() => {
      // Voice recovery is supplementary to text continuity.
    });
    return () => { cancelled = true; };
  }, [conversationId]);

  async function start() {
    const attempt = ++connectionAttemptRef.current;
    onError("");
    endingRef.current = false;
    mutedRef.current = false;
    setMuted(false);
    textDraftOwnerRef.current = null;
    setTextDraft("");
    callStartedAtRef.current = Date.now();
    setElapsedSeconds(0);
    setFamiliarActivity({ ...QUIET_VOICE_FEATURES, bands: [...QUIET_VOICE_FEATURES.bands] });
    setLines([]);
    setUsage(null);
    setEventNotice("");
    setApprovalCount(0);
    seenEventIdsRef.current.clear();
    pendingApprovalsRef.current.clear();
    setStatus("creating");
    try {
      const result = await client.createCall({
        conversation_id: conversationId ?? undefined,
        agent_profile_id: agentProfileId || undefined,
        model_profile_id: modelProfileId || undefined,
      });
      ensureConnectionAttempt(attempt);
      setCall(result.call);
      callRef.current = result.call;
      if (result.call.status === "realtime_unavailable") {
        setStatus(result.call.status);
        if (
          result.text_continuation_conversation_id
          && result.text_continuation_conversation_id !== conversationId
        ) {
          onConversation(result.text_continuation_conversation_id);
        }
        void refreshRecentCalls();
        window.setTimeout(() => onError("Live voice is unavailable. You can continue here in text."), 0);
        return;
      }
      if (result.call.conversation_id !== conversationId) {
        onConversation(result.call.conversation_id);
      }
      await connect(result, attempt);
      void refreshRecentCalls();
    } catch (reason) {
      if (connectionAttemptRef.current !== attempt) return;
      reportConnectionFailure(reason);
    }
  }

  async function reconnect() {
    const current = callRef.current;
    if (!current) return;
    const attempt = ++connectionAttemptRef.current;
    onError("");
    endingRef.current = false;
    setStatus("reconnecting");
    try {
      const result = await client.reopenCall(current.id);
      ensureConnectionAttempt(attempt);
      await connect(result, attempt);
      void refreshRecentCalls();
    } catch (reason) {
      if (connectionAttemptRef.current !== attempt) return;
      reportConnectionFailure(reason);
    }
  }

  async function resumeRecentCall(selected: RealtimeCall) {
    if (!isReopenable(selected.status)) return;
    const attempt = ++connectionAttemptRef.current;
    onError("");
    endingRef.current = false;
    closeMedia(mediaRef, readyRef, playAtRef);
    setLines([]);
    setUsage(null);
    setEventNotice("");
    setApprovalCount(0);
    textDraftOwnerRef.current = null;
    setTextDraft("");
    seenEventIdsRef.current.clear();
    pendingApprovalsRef.current.clear();
    setCall(selected);
    callRef.current = selected;
    setStatus("reconnecting");
    setRecovered(true);
    mutedRef.current = false;
    setMuted(false);
    callStartedAtRef.current = callStartMilliseconds(selected) ?? Date.now();
    if (selected.conversation_id !== conversationId) {
      onConversation(selected.conversation_id);
    }
    try {
      const result = await client.reopenCall(selected.id);
      ensureConnectionAttempt(attempt);
      await connect(result, attempt);
      void refreshRecentCalls();
    } catch (reason) {
      if (connectionAttemptRef.current !== attempt) return;
      reportConnectionFailure(reason);
    }
  }

  function reportConnectionFailure(reason: unknown) {
    if (reason instanceof VoiceConnectionCancelledError) return;
    setStatus(reason instanceof VoiceConnectionError ? reason.nextStatus : "failed");
    onError(reasonText(reason));
  }

  function ensureConnectionAttempt(attempt: number) {
    if (connectionAttemptRef.current !== attempt) {
      throw new VoiceConnectionCancelledError();
    }
  }

  async function connect(result: CallCreateResponse, attempt: number) {
    ensureConnectionAttempt(attempt);
    if (!result.media_token || !result.websocket_url) {
      throw new Error("The voice gateway did not issue a media session.");
    }
    closeMedia(mediaRef, readyRef, playAtRef);
    setCall(result.call);
    callRef.current = result.call;
    setStatus("joining");
    await restoreCallHistory(result.call.id, attempt);
    ensureConnectionAttempt(attempt);
    setStatus(pendingApprovalsRef.current.size > 0 ? "held" : "joining");

    let stream: MediaStream | null = null;
    let context: AudioContext | null = null;
    let source: MediaStreamAudioSourceNode | null = null;
    let processor: ScriptProcessorNode | null = null;
    let mute: GainNode | null = null;
    let micAnalyser: AnalyserNode | null = null;
    let socket: WebSocket | null = null;
    let resources: MediaResources | null = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
        video: false,
      });
      ensureConnectionAttempt(attempt);
      for (const track of audioTracks(stream)) track.enabled = !mutedRef.current;
      context = new AudioContext();
      playAtRef.current = 0;
      await context.resume();
      ensureConnectionAttempt(attempt);
      source = context.createMediaStreamSource(stream);
      processor = context.createScriptProcessor(4096, 1, 1);
      mute = context.createGain();
      mute.gain.value = 0;
      source.connect(processor);
      processor.connect(mute);
      mute.connect(context.destination);
      micAnalyser = attachBargeInCapture(context, source, mute);
      socket = new WebSocket(websocketUrl(result.websocket_url));
      ensureConnectionAttempt(attempt);
      socket.binaryType = "arraybuffer";
      resources = {
        socket,
        context,
        stream,
        processor,
        source,
        mute,
        playbackSources: new Set(),
        onPlayback: (speaking) => {
          const features = {
            ...QUIET_VOICE_FEATURES,
            bands: [...QUIET_VOICE_FEATURES.bands],
            speaking,
            level: speaking ? 0.6 : 0,
          };
          setFamiliarActivity(features);
          onFamiliarActivityRef.current?.(features);
        },
        analyser: createVoicePlaybackAnalyser(context),
        voiceTimer: null,
        prevSpectrum: null,
        onVoiceFeatures: (features) => {
          setFamiliarActivity(features);
          onFamiliarActivityRef.current?.(features);
        },
        ...bargeInHostFields(micAnalyser, () => interruptForBargeIn(
          mediaRef.current, playAtRef, setEventNotice,
        )),
        readyTimeout: null,
        rejectReady: null,
      };
      mediaRef.current = resources;
      startBargeInGate(resources, () => mutedRef.current);

      processor.onaudioprocess = (event) => {
        if (
          mutedRef.current
          || !readyRef.current
          || socket?.readyState !== WebSocket.OPEN
        ) return;
        const input = event.inputBuffer.getChannelData(0);
        const pcm = resamplePcm16(input, context?.sampleRate ?? 24_000, 24_000);
        if (pcm.byteLength) socket.send(pcm);
      };

      await new Promise<void>((resolve, reject) => {
        let settled = false;
        const settle = (reason?: Error) => {
          if (settled) return;
          settled = true;
          if (resources?.readyTimeout !== null && resources?.readyTimeout !== undefined) {
            window.clearTimeout(resources.readyTimeout);
            resources.readyTimeout = null;
          }
          if (resources) resources.rejectReady = null;
          if (reason) reject(reason);
          else resolve();
        };
        resources!.rejectReady = (reason) => settle(reason);
        resources!.readyTimeout = window.setTimeout(() => {
          const reason = new VoiceConnectionError(
            "Live voice did not become ready in time. The microphone was released; reconnect to try again.",
          );
          resources?.rejectReady?.(reason);
          if (mediaRef.current === resources) {
            closeMedia(mediaRef, readyRef, playAtRef);
          }
        }, VOICE_READY_TIMEOUT_MS);
        socket!.onopen = () => {
          try {
            socket!.send(JSON.stringify({
              type: "authenticate",
              media_token: result.media_token,
            }));
          } catch {
            const reason = new VoiceConnectionError(
              "The live voice session could not be authenticated. The microphone was released; reconnect to try again.",
            );
            resources?.rejectReady?.(reason);
            if (mediaRef.current === resources) {
              closeMedia(mediaRef, readyRef, playAtRef);
            }
          }
        };
        socket!.onmessage = (event) => {
          if (event.data instanceof ArrayBuffer) {
            if (readyRef.current && resources) {
              if (Date.now() < resources.suppressPlaybackUntil) return;
              playPcm(event.data, resources, playAtRef);
            }
            return;
          }
          if (typeof event.data !== "string") return;
          try {
            const message = JSON.parse(event.data) as {
              type?: string;
              call?: RealtimeCall;
              event?: IncomingCallEvent;
            };
            if (message.type === "ready") {
              readyRef.current = true;
              const nextStatus = pendingApprovalsRef.current.size > 0 ? "held" : "active";
              const active = {
                ...(message.call ?? result.call),
                status: nextStatus,
              } satisfies RealtimeCall;
              setCall(active);
              callRef.current = active;
              setStatus(nextStatus);
              setEventNotice((current) => current
                .replace(
                  "Voice will resume when the connection is ready.",
                  "Voice resumed.",
                )
                .replace(
                  "Waiting for the media connection to become ready.",
                  "Voice reconnected.",
                ));
              setRecovered(false);
              settle();
              void refreshRecentCalls();
              return;
            }
            const callEvent = message.event;
            if (message.type === "call_event" && callEvent?.type && callEvent.payload) {
              applyCallEvent(callEvent);
            }
          } catch {
            // Unknown control frames are ignored; binary PCM is handled above.
          }
        };
        socket!.onerror = () => {
          if (mediaRef.current !== resources || endingRef.current) return;
          const reason = readyRef.current
            ? new VoiceConnectionError(
              "The live voice connection was interrupted. Reconnect to continue.",
              "reconnecting",
            )
            : new VoiceConnectionError(
              "The live voice connection failed before it became ready. The microphone was released; reconnect to try again.",
            );
          const wasWaiting = resources?.rejectReady !== null;
          resources?.rejectReady?.(reason);
          closeMedia(mediaRef, readyRef, playAtRef);
          if (!wasWaiting) reportConnectionFailure(reason);
        };
        socket!.onclose = (event) => {
          // Ignore the late close callback from a socket deliberately replaced
          // by reconnect/end. A remote close releases the microphone immediately.
          if (mediaRef.current !== resources) return;
          const reason = socketCloseError(event);
          const wasWaiting = resources?.rejectReady !== null;
          resources?.rejectReady?.(reason);
          closeMedia(mediaRef, readyRef, playAtRef);
          if (
            !wasWaiting
            && !endingRef.current
            && callRef.current?.status !== "ended"
          ) {
            reportConnectionFailure(reason);
          }
        };
      });
      ensureConnectionAttempt(attempt);
    } catch (reason) {
      if (resources && mediaRef.current === resources) {
        closeMedia(mediaRef, readyRef, playAtRef);
      } else if (!resources) {
        closePartialMedia({ socket, context, stream, processor, source, mute, micAnalyser });
        playAtRef.current = 0;
      }
      throw reason;
    }
  }

  async function end() {
    const current = callRef.current;
    const attempt = ++connectionAttemptRef.current;
    endingRef.current = true;
    closeMedia(mediaRef, readyRef, playAtRef);
    if (!current) {
      setStatus("idle");
      return;
    }
    try {
      const ended = await client.endCall(current.id);
      ensureConnectionAttempt(attempt);
      setCall(ended);
      callRef.current = ended;
      setStatus("ended");
      mutedRef.current = false;
      setMuted(false);
      setEventNotice("Call ended.");
      await Promise.all([
        refreshUsage(current.id, attempt),
        restoreCallHistory(current.id, attempt),
        refreshRecentCalls(),
      ]);
    } catch (reason) {
      if (connectionAttemptRef.current !== attempt) return;
      setStatus("failed");
      onError(reasonText(reason));
    }
  }

  endCallRef.current = end;

  function toggleMute() {
    const next = !mutedRef.current;
    mutedRef.current = next;
    setMuted(next);
    const stream = mediaRef.current?.stream;
    if (!stream) return;
    for (const track of audioTracks(stream)) track.enabled = !next;
  }

  function sendTextMessage() {
    const text = textDraft.trim();
    const owner = textDraftOwnerRef.current;
    if (
      text
      && (
        owner?.conversationId !== conversationId
        || owner.callId !== (callRef.current?.id ?? null)
      )
    ) {
      textDraftOwnerRef.current = null;
      setTextDraft("");
      return;
    }
    const socket = mediaRef.current?.socket;
    if (!text || !readyRef.current || socket?.readyState !== WebSocket.OPEN) return;
    try {
      // Typed mid-call text rides the same media socket as the mic PCM; the
      // gateway injects it into the provider session and echoes it back as a
      // transcript call_event, which is what renders the line.
      socket.send(JSON.stringify({ type: "user_text", text }));
      textDraftOwnerRef.current = null;
      setTextDraft("");
    } catch {
      // A dying socket reports itself through its own close/error handling.
    }
  }

  async function refreshRecentCalls() {
    if (typeof client.calls !== "function") return;
    try {
      setRecentCalls((await client.calls(10)).calls);
    } catch {
      // Recent calls are supplementary to the live voice controls.
    }
  }

  function isCurrentCallGeneration(callId: string, attempt: number) {
    return connectionAttemptRef.current === attempt
      && callRef.current?.id === callId;
  }

  async function refreshUsage(
    callId: string,
    attempt = connectionAttemptRef.current,
  ) {
    try {
      const result = await client.callUsage(callId);
      if (!isCurrentCallGeneration(callId, attempt)) return;
      setUsage(result.usage);
    } catch {
      // Usage is supplementary to the call. Its absence must not turn an
      // otherwise successful voice session into a failed one.
    }
  }

  async function restoreCallHistory(
    callId: string,
    attempt = connectionAttemptRef.current,
  ) {
    try {
      const history = await client.callEvents(callId);
      if (!isCurrentCallGeneration(callId, attempt)) return;
      let includesUsage = false;
      for (const event of history.events) {
        includesUsage ||= event.type === "usage";
        applyCallEvent(event, false);
      }
      if (includesUsage) await refreshUsage(callId, attempt);
    } catch {
      if (!isCurrentCallGeneration(callId, attempt)) return;
      setEventNotice("Call history could not be restored. New live events will still appear.");
    }
  }

  function updateCallStatus(nextStatus: CallStatus) {
    setStatus(nextStatus);
    setCall((current) => {
      if (!current) return current;
      const updated = { ...current, status: nextStatus };
      callRef.current = updated;
      return updated;
    });
  }

  function applyCallEvent(event: IncomingCallEvent, refreshUsageEvent = true) {
    if (event.id) {
      if (seenEventIdsRef.current.has(event.id)) return;
      seenEventIdsRef.current.add(event.id);
    }
    const payload = event.payload;
    if (event.type === "transcript" && typeof payload.text === "string") {
      const line: VoiceLine = {
        id: event.id ?? crypto.randomUUID(),
        speaker: payload.kind === "input" ? "You" : "Boltrig",
        text: payload.text,
        typed: payload.via === "text",
      };
      setLines((current) => [...current, line].slice(-50));
      return;
    }
    if (event.type === "usage") {
      const activeCallId = event.call_id ?? callRef.current?.id;
      if (activeCallId && refreshUsageEvent) void refreshUsage(activeCallId);
      return;
    }
    if (event.type === "hitl") {
      const requestId = typeof payload.request_id === "string" ? payload.request_id : "";
      const approvalStatus = typeof payload.status === "string" ? payload.status : "pending";
      const verb = typeof payload.verb === "string" ? payload.verb : "the requested action";
      if (approvalStatus === "pending") {
        if (requestId) pendingApprovalsRef.current.add(requestId);
        setApprovalCount(pendingApprovalsRef.current.size || 1);
        updateCallStatus("held");
        setEventNotice(`Approval needed for ${verb}. Review it in the originating chat to continue.`);
      } else {
        if (requestId) pendingApprovalsRef.current.delete(requestId);
        setApprovalCount(pendingApprovalsRef.current.size);
        updateCallStatus(
          pendingApprovalsRef.current.size > 0
            ? "held"
            : readyRef.current ? "active" : "joining",
        );
        setEventNotice(
          approvalStatus === "ok"
            ? readyRef.current
              ? "Approval granted. Voice resumed."
              : "Approval granted. Voice will resume when the connection is ready."
            : readyRef.current
              ? `The action was ${approvalStatus}. Voice resumed without it.`
              : `The action was ${approvalStatus}. Voice will resume without it when the connection is ready.`,
        );
      }
      return;
    }
    if (event.type === "reconnected") {
      if (pendingApprovalsRef.current.size === 0) {
        updateCallStatus(readyRef.current ? "active" : "joining");
      }
      setEventNotice(readyRef.current
        ? "Voice reconnected."
        : "Waiting for the media connection to become ready.");
      return;
    }
    if (event.type === "interrupted") {
      stopQueuedPlayback(mediaRef.current, playAtRef);
      setEventNotice(BARGE_IN_NOTICE);
      return;
    }
    if (event.type === "ended") {
      updateCallStatus("ended");
      setEventNotice("Call ended.");
      void refreshRecentCalls();
    }
  }

  if (status === "idle" || status === "realtime_unavailable") {
    return (
      <div className={`voice-idle${embedded ? " voice-idle-embedded" : ""}`}>
        {call && usage && <CallReceipt usage={usage} />}
        <button
          aria-label={embedded ? "Talk to the chief of staff" : undefined}
          className="primary-button"
          onClick={() => void start()}
          title={embedded ? "Talk to the chief of staff instead" : undefined}
          type="button"
        >
          {embedded ? (
            <svg aria-hidden fill="currentColor" height="15" viewBox="0 0 24 24" width="15">
              <rect height="4" rx="1.1" width="2.2" x="4" y="10" />
              <rect height="10" rx="1.1" width="2.2" x="8.2" y="7" />
              <rect height="15" rx="1.1" width="2.2" x="12.4" y="4.5" />
              <rect height="6" rx="1.1" width="2.2" x="16.6" y="9" />
            </svg>
          ) : "◉ Start call"}
        </button>
        {showOptions && <details className="voice-options">
          <summary>Call options</summary>
          <div className="voice-options-body">
            <RecentCalls
              calls={recentCalls}
              currentCallId={call?.id}
              currentStatus={status}
              onResume={resumeRecentCall}
            />
            {agentProfiles.length > 0 && (
              <label className="voice-profile">
                <span className="sr-only">Voice agent</span>
                <select
                  aria-label="Voice agent"
                  value={agentProfileId}
                  onChange={(event) => setAgentProfileId(event.target.value)}
                >
                  <option value="">Default voice</option>
                  {agentProfiles.map((profile) => (
                    <option key={profile.name} value={profile.name}>{profile.name}</option>
                  ))}
                </select>
              </label>
            )}
          </div>
        </details>}
      </div>
    );
  }

  if (status === "ended") {
    return (
      <section className="voice-call voice-call-ended" aria-live="polite">
        <div className="voice-call-heading">
          <span className="voice-dot" />
          <strong>Call ended</strong>
        </div>
        {eventNotice && <p className="voice-event-notice" role="status">{eventNotice}</p>}
        <VoiceTranscript lines={lines} />
        <div className="voice-actions">
          {call && usage && <CallReceipt usage={usage} />}
          {showOptions && (
            <RecentCalls
              calls={recentCalls}
              currentCallId={call?.id}
              currentStatus={status}
              onResume={resumeRecentCall}
            />
          )}
          <button className="secondary-button compact-button" onClick={() => void start()}>
            Start another call
          </button>
        </div>
      </section>
    );
  }

  const agentParticipants = call?.participants.filter(
    (participant) => participant.kind === "agent",
  ) ?? [];
  const primaryAgent = agentParticipants[0];
  const focusedAgent = agentParticipants.find(
    (participant) => participant.id === focusedParticipantId,
  ) ?? primaryAgent;
  const otherAgents = agentParticipants
    .filter((participant) => participant.id !== focusedAgent?.id)
    .slice(0, 3);
  const profileGenotype = agentProfiles.find(
    (profile) => profile.name === call?.agent_profile_id,
  )?.familiar_genotype;
  const focusedGenotype = focusedAgent?.familiar_genotype
    ?? (focusedAgent?.id === primaryAgent?.id ? profileGenotype : null);
  const latestAssistantLine = [...lines].reverse().find(
    (line) => line.speaker === "Boltrig",
  );
  const latestTypedLine = [...lines].reverse().find((line) => line.typed);
  const focusedOnPrimary = focusedAgent?.id === primaryAgent?.id;
  const stageState = {
    working: focusedOnPrimary && !familiarActivity.speaking && (
      status === "creating" || status === "joining" || status === "reconnecting"
    ),
    speaking: focusedOnPrimary && familiarActivity.speaking,
    level: focusedOnPrimary ? familiarActivity.level : 0,
    bands: focusedOnPrimary ? familiarActivity.bands : QUIET_VOICE_FEATURES.bands,
    onset: focusedOnPrimary ? familiarActivity.onset : 0,
  };
  const stageInput: StageTurnInput = {
    loading: false,
    hasLiveEvents: stageState.working,
    liveEnded: false,
    voiceSpeaking: stageState.speaking,
    voiceLevel: stageState.level,
    voiceBands: stageState.bands,
    voiceOnset: stageState.onset,
    micActive: !muted,
  };
  const noticeVisible = Boolean(eventNotice && eventNotice !== dismissedNotice);
  const primaryAgentPhrase = callParticipantPhrase(primaryAgent?.label ?? "Boltrig");
  const callScreen = (
    <section
      aria-label="Voice call"
      aria-modal="true"
      className="voice-call-screen"
      data-screen-label="Call"
      ref={callScreenRef}
      role="dialog"
      tabIndex={-1}
    >
      <header className="voice-call-screen-header">
        <div className="voice-call-title">
          {conversationTitle
            ? `${conversationTitle} · you and ${primaryAgentPhrase}`
            : `Voice call · you and ${primaryAgentPhrase}`}
        </div>
        <time className="voice-call-elapsed" dateTime={`PT${elapsedSeconds}S`}>
          {formatElapsed(elapsedSeconds)}
        </time>
        <button className="voice-call-leave" onClick={() => void end()} type="button">
          Leave
        </button>
      </header>

      <div className="voice-call-freezone">
        {noticeVisible && (
          <article
            className="voice-call-notice"
            data-urgent={approvalCount > 0 ? "true" : "false"}
            role="status"
          >
            <div className="voice-call-notice-header">
              <span>{approvalCount > 0 ? "Waiting for you" : "Voice connection"}</span>
              <button
                aria-label="Dismiss call notice"
                onClick={() => setDismissedNotice(eventNotice)}
                type="button"
              >
                ×
              </button>
            </div>
            <p>{eventNotice}</p>
          </article>
        )}

        <div className="voice-call-presence">
          <div className="voice-call-primary-familiar">
            <StageBody
              genotype={focusedGenotype}
              input={stageInput}
              label={focusedAgent?.label ?? "Boltrig"}
              mode="voice"
              phenotype={stagePhenotype}
            />
          </div>
          <strong>{focusedAgent?.label ?? "Boltrig"}</strong>
          {latestAssistantLine && focusedOnPrimary && (
            <p className="voice-call-saying">{latestAssistantLine.text}</p>
          )}
          {latestTypedLine && (
            <p className="voice-call-typed">You typed: {latestTypedLine.text}</p>
          )}
          {!focusedOnPrimary && (
            <span className="sr-only" role="status">
              Viewing {focusedAgent?.label}. Call audio and routing are unchanged.
            </span>
          )}
          <p className="voice-call-state" aria-live="polite">{voiceStatus(status)}</p>
        </div>

        <div className="voice-call-transcript-sr">
          <VoiceTranscript
            lines={latestAssistantLine && focusedOnPrimary
              ? lines.filter((line) => line.id !== latestAssistantLine.id)
              : lines}
          />
        </div>
      </div>

      <footer className="voice-call-screen-footer">
        <div className="voice-call-participants" aria-label="Other agents in this call">
          {otherAgents.map((participant) => (
            <button
              aria-label={`Show ${participant.label} in the call centre`}
              className="voice-call-participant"
              key={participant.id}
              onClick={() => setFocusedParticipantId(participant.id)}
              type="button"
            >
              <FamiliarBadge
                genotype={participant.familiar_genotype}
                label={participant.label}
                size={30}
                state="ready"
              />
              <span>{participant.label}</span>
            </button>
          ))}
        </div>
        <div className="voice-call-controls">
          {(status === "active" || status === "held") && (
            <form
              className="voice-call-text"
              onSubmit={(event) => {
                event.preventDefault();
                sendTextMessage();
              }}
            >
              <input
                aria-label="Type a message to the call"
                onChange={(event) => {
                  const value = event.target.value;
                  textDraftOwnerRef.current = value ? {
                    conversationId,
                    callId: callRef.current?.id ?? null,
                  } : null;
                  setTextDraft(value);
                }}
                placeholder="Type a message…"
                value={textDraft}
              />
              <button disabled={!textDraft.trim()} type="submit">Send</button>
            </form>
          )}
          {(recovered || status === "reconnecting" || status === "failed") && (
            <button onClick={() => void reconnect()} type="button">
              {recovered ? "Resume call" : "Reconnect"}
            </button>
          )}
          <button
            aria-pressed={muted}
            onClick={toggleMute}
            type="button"
          >
            {muted ? "Unmute" : "Mute"}
          </button>
        </div>
      </footer>
    </section>
  );

  return typeof document === "undefined"
    ? callScreen
    : createPortal(callScreen, document.body);
}

function RecentCalls({
  calls,
  currentCallId,
  currentStatus,
  onResume,
}: {
  calls: RealtimeCall[];
  currentCallId?: string;
  currentStatus: CallStatus | "idle";
  onResume(call: RealtimeCall): Promise<void>;
}) {
  return (
    <details className="recent-calls">
      <summary>Recent calls{calls.length > 0 ? ` · ${calls.length}` : ""}</summary>
      <div className="recent-call-list" aria-label="Recent voice calls">
        {calls.length === 0 && <p>No recent calls.</p>}
        {calls.map((item) => {
          const timestamp = callTimestamp(item);
          const currentIsConnected = item.id === currentCallId
            && ["creating", "joining", "active", "held"].includes(currentStatus);
          return (
            <article className="recent-call" key={item.id}>
              <div className="recent-call-heading">
                <strong>{historyStatus(item.status)}</strong>
                {timestamp && (
                  <time dateTime={timestamp.value}>
                    {timestamp.label} {formatCallTimestamp(timestamp.value)}
                  </time>
                )}
              </div>
              <p>
                Agent: {item.agent_profile_id ?? "Default"}
                {" · "}
                Model: {item.model_profile_id ?? "Default"}
              </p>
              {isReopenable(item.status) && (
                currentIsConnected
                  ? <span className="recent-call-current">Current call</span>
                  : (
                    <button
                      className="secondary-button compact-button"
                      aria-label={`Resume recent call ${item.id}`}
                      onClick={() => void onResume(item)}
                    >
                      Resume call
                    </button>
                  )
              )}
            </article>
          );
        })}
      </div>
    </details>
  );
}

function VoiceTranscript({ lines }: { lines: VoiceLine[] }) {
  if (lines.length === 0) return null;
  return (
    <div className="voice-transcript" aria-label="Call transcript">
      {lines.map((line) => (
        <p key={line.id}><b>{line.speaker}:</b> {line.text}</p>
      ))}
    </div>
  );
}

function CallReceipt({ usage }: { usage: CallUsage }) {
  const inputSeconds = usage.input_audio_bytes / 48_000;
  const outputSeconds = usage.output_audio_bytes / 48_000;
  const duration = inputSeconds + outputSeconds;
  const cost = usage.cost_status === "estimated"
    ? `Estimated ${formatMicros(usage.estimated_cost_micros)}`
    : "Cost unpriced";
  return (
    <details className="call-receipt">
      <summary>Call receipt · {cost}</summary>
      <dl>
        <div><dt>Audio processed</dt><dd>{formatDuration(duration)}</dd></div>
        <div><dt>Provider tokens</dt><dd>{usage.provider_input_tokens + usage.provider_output_tokens}</dd></div>
        <div><dt>Tool calls</dt><dd>{usage.tool_calls}</dd></div>
        <div><dt>Pricing</dt><dd>{usage.pricing_revision ?? "No configured rate"}</dd></div>
      </dl>
      {usage.cost_status === "estimated" && <p>Internal estimate, not a provider invoice.</p>}
    </details>
  );
}

function isReopenable(status: CallStatus) {
  return ["creating", "joining", "active", "reconnecting", "held"].includes(status);
}

function callTimestamp(call: RealtimeCall) {
  if (call.ended_at) return { label: "Ended", value: call.ended_at };
  if (call.started_at) return { label: "Started", value: call.started_at };
  if (call.updated_at) return { label: "Updated", value: call.updated_at };
  if (call.created_at) return { label: "Created", value: call.created_at };
  return null;
}

function formatCallTimestamp(value: string) {
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.getTime()) ? value : timestamp.toLocaleString();
}

function historyStatus(status: CallStatus) {
  if (status === "realtime_unavailable") return "Voice unavailable";
  if (status === "reconnecting") return "Paused";
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function formatDuration(seconds: number) {
  if (seconds < 1) return `${Math.round(seconds * 1_000)} ms`;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

function callStartMilliseconds(call: RealtimeCall | null): number | null {
  const value = call?.started_at ?? call?.created_at;
  if (!value) return null;
  const milliseconds = new Date(value).getTime();
  return Number.isFinite(milliseconds) ? milliseconds : null;
}

function formatElapsed(totalSeconds: number) {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function callParticipantPhrase(label: string) {
  const trimmed = label.trim() || "Boltrig";
  return /^[a-z]/.test(trimmed) && !/^(?:a|an|the)\s/i.test(trimmed)
    ? `the ${trimmed}`
    : trimmed;
}

function modalFocusableElements(dialog: HTMLElement): HTMLElement[] {
  const selector = [
    "a[href]",
    "area[href]",
    "button:not([disabled])",
    "input:not([disabled]):not([type='hidden'])",
    "select:not([disabled])",
    "textarea:not([disabled])",
    "iframe",
    "object",
    "embed",
    "[contenteditable='true']",
    "[tabindex]:not([tabindex='-1'])",
  ].join(",");
  return [...dialog.querySelectorAll<HTMLElement>(selector)].filter((element) => {
    if (element.closest("[hidden], [inert], [aria-hidden='true']")) return false;
    const style = window.getComputedStyle(element);
    return style.display !== "none" && style.visibility !== "hidden";
  });
}

function restoreAttribute(
  element: HTMLElement,
  name: "aria-hidden" | "inert",
  value: string | null,
) {
  if (value === null) element.removeAttribute(name);
  else element.setAttribute(name, value);
}

function formatMicros(value: number) {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: value < 10_000 ? 4 : 2,
    maximumFractionDigits: value < 10_000 ? 4 : 2,
  }).format(value / 1_000_000);
}

function closeMedia(
  ref: MutableRefObject<MediaResources | null>,
  ready: MutableRefObject<boolean>,
  playAt: MutableRefObject<number>,
) {
  ready.current = false;
  const media = ref.current;
  ref.current = null;
  playAt.current = 0;
  if (!media) return;
  stopVoiceSampler(media);
  stopBargeInGate(media);
  media.suppressPlaybackUntil = 0;
  if (media.micAnalyser) safeDisconnect(media.micAnalyser);
  try {
    media.analyser?.disconnect();
  } catch {
    // context may already be closed
  }
  media.rejectReady?.(new VoiceConnectionCancelledError());
  media.rejectReady = null;
  if (media.readyTimeout !== null) {
    window.clearTimeout(media.readyTimeout);
    media.readyTimeout = null;
  }
  media.processor.onaudioprocess = null;
  media.socket.onopen = null;
  media.socket.onmessage = null;
  media.socket.onerror = null;
  media.socket.onclose = null;
  stopQueuedPlayback(media, playAt);
  safeDisconnect(media.processor);
  safeDisconnect(media.source);
  safeDisconnect(media.mute);
  for (const track of media.stream.getTracks()) {
    try {
      track.stop();
    } catch {
      // Continue releasing the remaining media resources.
    }
  }
  if (
    media.socket.readyState === WebSocket.OPEN
    || media.socket.readyState === WebSocket.CONNECTING
  ) {
    try {
      media.socket.close(1000, "client closed");
    } catch {
      // The socket is already unusable; the other resources still need release.
    }
  }
  try {
    void media.context.close().catch(() => {
      // The context may already be closed by the browser.
    });
  } catch {
    // The context may already be closed by the browser.
  }
  playAt.current = 0;
}

function closePartialMedia({
  socket,
  context,
  stream,
  processor,
  source,
  mute,
  micAnalyser,
}: {
  socket: WebSocket | null;
  context: AudioContext | null;
  stream: MediaStream | null;
  processor: ScriptProcessorNode | null;
  source: MediaStreamAudioSourceNode | null;
  mute: GainNode | null;
  micAnalyser: AnalyserNode | null;
}) {
  if (processor) {
    processor.onaudioprocess = null;
    safeDisconnect(processor);
  }
  if (source) safeDisconnect(source);
  if (mute) safeDisconnect(mute);
  if (micAnalyser) safeDisconnect(micAnalyser);
  for (const track of stream?.getTracks() ?? []) {
    try {
      track.stop();
    } catch {
      // Continue releasing the remaining setup resources.
    }
  }
  if (
    socket
    && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)
  ) {
    try {
      socket.close(1000, "setup failed");
    } catch {
      // The socket was never usable.
    }
  }
  if (context) {
    try {
      void context.close().catch(() => {
        // The context may have failed while resuming.
      });
    } catch {
      // The context may have failed while resuming.
    }
  }
}

function interruptForBargeIn(
  media: MediaResources | null,
  playAt: MutableRefObject<number>,
  setNotice: (notice: string) => void,
) {
  if (!media) return;
  stopQueuedPlayback(media, playAt);
  setNotice(BARGE_IN_NOTICE);
  requestSelfHostedInterrupt();
}

function stopQueuedPlayback(
  media: MediaResources | null,
  playAt: MutableRefObject<number>,
) {
  if (!media) {
    playAt.current = 0;
    return;
  }
  for (const source of media.playbackSources) {
    source.onended = null;
    try {
      source.stop();
    } catch {
      // A source that ended between the event and cleanup is already stopped.
    }
    safeDisconnect(source);
  }
  media.playbackSources.clear();
  stopVoiceSampler(media);
  media.onPlayback?.(false);
  playAt.current = media.context.currentTime;
}

function websocketUrl(value: string): string {
  // The kernel's default websocket_url is relative and same-origin, which is
  // what the web edge proxies. The desktop shell's document is tauri://localhost
  // and serves no gateway, so there the relative URL belongs to the configured
  // API origin the device session is already bound to.
  const origin = isDesktop ? configuredApiOrigin() : "";
  const url = new URL(value, origin || window.location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

function playPcm(
  bytes: ArrayBuffer,
  media: MediaResources,
  playAt: MutableRefObject<number>,
) {
  const pcm = new Int16Array(bytes);
  if (!pcm.length) return;
  const { context } = media;
  const buffer = context.createBuffer(1, pcm.length, 24_000);
  const channel = buffer.getChannelData(0);
  for (let index = 0; index < pcm.length; index += 1) {
    channel[index] = (pcm[index] ?? 0) / 0x8000;
  }
  const source = context.createBufferSource();
  source.buffer = buffer;
  source.connect(media.analyser ?? context.destination);
  media.playbackSources.add(source);
  media.onPlayback?.(true);
  startVoiceSampler(media);
  source.onended = () => {
    media.playbackSources.delete(source);
    safeDisconnect(source);
    media.onPlayback?.(media.playbackSources.size > 0);
  };
  const startsAt = Math.max(context.currentTime, playAt.current);
  source.start(startsAt);
  playAt.current = startsAt + buffer.duration;
}

function socketCloseError(event: CloseEvent): VoiceConnectionError {
  if (event.code === 4429) {
    return new VoiceConnectionError(
      "Live voice is at capacity. Your text conversation is unaffected; try reconnecting shortly.",
    );
  }
  if (event.code === 4401) {
    return new VoiceConnectionError(
      "The one-time voice session expired. Reconnect to request a fresh session.",
      "reconnecting",
    );
  }
  if (event.code === 1013) {
    return new VoiceConnectionError(
      "The voice provider is temporarily unavailable. You can continue in text or reconnect.",
    );
  }
  return new VoiceConnectionError(
    "The live voice connection closed. Reconnect to continue.",
    "reconnecting",
  );
}

function voiceStatus(status: CallStatus | "idle") {
  if (status === "active") return "Live voice";
  if (status === "held") return "Waiting for approval";
  if (status === "joining") return "Joining…";
  if (status === "reconnecting") return "Connection paused";
  if (status === "failed") return "Call interrupted";
  if (status === "ended") return "Call ended";
  return "Preparing voice…";
}

function reasonText(reason: unknown) {
  return reason instanceof Error ? reason.message : "Unable to start the voice call.";
}
