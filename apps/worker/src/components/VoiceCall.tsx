import { useEffect, useRef, useState } from "react";
import type { MutableRefObject } from "react";
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

interface VoiceCallProps {
  conversationId: string | null;
  modelProfileId?: string;
  onConversation(id: string): void;
  onError(message: string): void;
}

interface VoiceLine {
  id: string;
  speaker: "You" | "Boltrig";
  text: string;
}

type IncomingCallEvent = Pick<CallEvent, "type" | "payload"> &
  Partial<Pick<CallEvent, "id" | "call_id" | "participant_id" | "created_at">>;

interface MediaResources {
  socket: WebSocket;
  context: AudioContext;
  stream: MediaStream;
  processor: ScriptProcessorNode;
  source: MediaStreamAudioSourceNode;
  mute: GainNode;
  playbackSources: Set<AudioBufferSourceNode>;
  readyTimeout: number | null;
  rejectReady: ((reason: Error) => void) | null;
}

const VOICE_READY_TIMEOUT_MS = 15_000;

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
  modelProfileId,
  onConversation,
  onError,
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
  const mediaRef = useRef<MediaResources | null>(null);
  const callRef = useRef<RealtimeCall | null>(null);
  const readyRef = useRef(false);
  const endingRef = useRef(false);
  const connectionAttemptRef = useRef(0);
  const playAtRef = useRef(0);
  const seenEventIdsRef = useRef(new Set<string>());
  const pendingApprovalsRef = useRef(new Set<string>());

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
    connectionAttemptRef.current += 1;
    closeMedia(mediaRef, readyRef, playAtRef);
    callRef.current = null;
    setCall(null);
    setStatus("idle");
    setRecovered(false);
    setLines([]);
    seenEventIdsRef.current.clear();
    if (!conversationId) return () => { cancelled = true; };
    if (typeof client.currentCall !== "function") {
      return () => { cancelled = true; };
    }
    void client.currentCall(conversationId).then(async (result) => {
      if (cancelled || !result.call) return;
      setCall(result.call);
      callRef.current = result.call;
      setStatus("reconnecting");
      setRecovered(true);
      setEventNotice("A voice call from this conversation can be resumed.");
      await restoreCallHistory(result.call.id);
    }).catch(() => {
      // Voice recovery is supplementary to text continuity.
    });
    return () => { cancelled = true; };
  }, [conversationId]);

  async function start() {
    const attempt = ++connectionAttemptRef.current;
    onError("");
    endingRef.current = false;
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
        onError("Live voice is unavailable. You can continue here in text.");
        return;
      }
      if (result.call.conversation_id !== conversationId) {
        onConversation(result.call.conversation_id);
      }
      await connect(result, attempt);
      void refreshRecentCalls();
    } catch (reason) {
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
    seenEventIdsRef.current.clear();
    pendingApprovalsRef.current.clear();
    setCall(selected);
    callRef.current = selected;
    setStatus("reconnecting");
    setRecovered(true);
    if (selected.conversation_id !== conversationId) {
      onConversation(selected.conversation_id);
    }
    try {
      const result = await client.reopenCall(selected.id);
      ensureConnectionAttempt(attempt);
      await connect(result, attempt);
      void refreshRecentCalls();
    } catch (reason) {
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
    await restoreCallHistory(result.call.id);
    ensureConnectionAttempt(attempt);
    setStatus(pendingApprovalsRef.current.size > 0 ? "held" : "joining");

    let stream: MediaStream | null = null;
    let context: AudioContext | null = null;
    let source: MediaStreamAudioSourceNode | null = null;
    let processor: ScriptProcessorNode | null = null;
    let mute: GainNode | null = null;
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
        readyTimeout: null,
        rejectReady: null,
      };
      mediaRef.current = resources;

      processor.onaudioprocess = (event) => {
        if (!readyRef.current || socket?.readyState !== WebSocket.OPEN) return;
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
        closePartialMedia({ socket, context, stream, processor, source, mute });
        playAtRef.current = 0;
      }
      throw reason;
    }
  }

  async function end() {
    const current = callRef.current;
    connectionAttemptRef.current += 1;
    endingRef.current = true;
    closeMedia(mediaRef, readyRef, playAtRef);
    if (!current) {
      setStatus("idle");
      return;
    }
    try {
      const ended = await client.endCall(current.id);
      setCall(ended);
      callRef.current = ended;
      setStatus("ended");
      setEventNotice("Call ended.");
      await Promise.all([
        refreshUsage(current.id),
        restoreCallHistory(current.id),
        refreshRecentCalls(),
      ]);
    } catch (reason) {
      setStatus("failed");
      onError(reasonText(reason));
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

  async function refreshUsage(callId: string) {
    try {
      setUsage((await client.callUsage(callId)).usage);
    } catch {
      // Usage is supplementary to the call. Its absence must not turn an
      // otherwise successful voice session into a failed one.
    }
  }

  async function restoreCallHistory(callId: string) {
    try {
      const history = await client.callEvents(callId);
      let includesUsage = false;
      for (const event of history.events) {
        includesUsage ||= event.type === "usage";
        applyCallEvent(event, false);
      }
      if (includesUsage) await refreshUsage(callId);
    } catch {
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
        setEventNotice(`Approval needed for ${verb}. Review it in Inbox to continue.`);
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
      setEventNotice("Playback stopped while you were speaking.");
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
      <div className="voice-idle">
        {call && usage && <CallReceipt usage={usage} />}
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
        <button className="secondary-button" onClick={() => void start()}>
          ◉ Start call
        </button>
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
          <RecentCalls
            calls={recentCalls}
            currentCallId={call?.id}
            currentStatus={status}
            onResume={resumeRecentCall}
          />
          <button className="secondary-button compact-button" onClick={() => void start()}>
            Start another call
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className="voice-call" aria-live="polite">
      <div className="voice-call-heading">
        <span className={`voice-dot ${status === "active" ? "is-live" : ""}`} />
        <strong>{voiceStatus(status)}</strong>
        {call?.participants.filter((participant) => participant.kind === "agent").map((participant) => (
          <span
            className="mini-familiar"
            style={participantPalette(participant.familiar_genotype?.palette)}
            title={participant.label}
            aria-label={`${participant.label} familiar`}
            key={participant.id}
          />
        ))}
      </div>
      {eventNotice && (
        <p className={approvalCount > 0 ? "voice-event-notice approval" : "voice-event-notice"} role="status">
          {eventNotice}
          {approvalCount > 0 && <> <a href="#/inbox">Open Inbox</a></>}
        </p>
      )}
      <VoiceTranscript lines={lines} />
      <div className="voice-actions">
        <RecentCalls
          calls={recentCalls}
          currentCallId={call?.id}
          currentStatus={status}
          onResume={resumeRecentCall}
        />
        {(recovered || status === "reconnecting" || status === "failed") && (
          <button className="secondary-button compact-button" onClick={() => void reconnect()}>
            {recovered ? "Resume call" : "Reconnect"}
          </button>
        )}
        <button className="danger-button compact-button" onClick={() => void end()}>
          End
        </button>
      </div>
    </section>
  );
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

function formatMicros(value: number) {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: value < 10_000 ? 4 : 2,
    maximumFractionDigits: value < 10_000 ? 4 : 2,
  }).format(value / 1_000_000);
}

function participantPalette(palette?: string[] | null): React.CSSProperties {
  const colors = (palette ?? [])
    .filter((value) => /^#[0-9a-f]{3,8}$/i.test(value))
    .slice(0, 3);
  if (colors.length === 0) return {};
  if (colors.length === 1) return { background: colors[0] };
  return { background: `radial-gradient(circle at 35% 30%, ${colors.join(", ")})` };
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
}: {
  socket: WebSocket | null;
  context: AudioContext | null;
  stream: MediaStream | null;
  processor: ScriptProcessorNode | null;
  source: MediaStreamAudioSourceNode | null;
  mute: GainNode | null;
}) {
  if (processor) {
    processor.onaudioprocess = null;
    safeDisconnect(processor);
  }
  if (source) safeDisconnect(source);
  if (mute) safeDisconnect(mute);
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

function safeDisconnect(node: AudioNode) {
  try {
    node.disconnect();
  } catch {
    // Disconnect is best-effort for nodes whose setup never completed.
  }
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

function resamplePcm16(
  input: Float32Array,
  inputRate: number,
  outputRate: number,
): ArrayBuffer {
  const ratio = inputRate / outputRate;
  const length = Math.max(1, Math.floor(input.length / ratio));
  const output = new Int16Array(length);
  for (let index = 0; index < length; index += 1) {
    const from = Math.floor(index * ratio);
    const to = Math.min(input.length, Math.floor((index + 1) * ratio));
    let sum = 0;
    for (let cursor = from; cursor < to; cursor += 1) sum += input[cursor] ?? 0;
    const sample = Math.max(-1, Math.min(1, sum / Math.max(1, to - from)));
    output[index] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return output.buffer;
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
  source.connect(context.destination);
  media.playbackSources.add(source);
  source.onended = () => {
    media.playbackSources.delete(source);
    safeDisconnect(source);
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
