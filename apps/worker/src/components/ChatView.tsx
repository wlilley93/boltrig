import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  BoltrigApiError,
  normalizeEvents,
  type Artifact,
  type ChatAttachment,
  type ChatAttachmentLimits,
  type ChatEvent,
  type ChatMessage,
  type ConversationModelContext,
  type FamiliarGenotype,
  type ModelProfile,
  type NormalizedTurn,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import {
  materializeArtifact,
  openMaterializedArtifact,
  revealMaterializedArtifact,
} from "../desktop";
import { ConversationControls } from "./ConversationControls";
import { LiveQuestionCard } from "./LiveQuestionCard";
import { VoiceCall } from "./VoiceCall";

interface ChatViewProps {
  conversationId: string | null;
  onConversation(id: string): void;
  onChanged(): void;
}

const DEFAULT_ATTACHMENT_LIMITS: ChatAttachmentLimits = {
  max_count: 8,
  max_bytes: 256 * 1_024,
  max_total_bytes: 1_024 * 1_024,
  model_readable_media_types: ["text/*"],
};

export function ChatView({ conversationId, onConversation, onChanged }: ChatViewProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [events, setEvents] = useState<ChatEvent[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [artifactCursor, setArtifactCursor] = useState<string | null>(null);
  const [loadingArtifacts, setLoadingArtifacts] = useState(false);
  const [profiles, setProfiles] = useState<ModelProfile[]>([]);
  const [attachmentLimits, setAttachmentLimits] = useState(DEFAULT_ATTACHMENT_LIMITS);
  const [attachmentLimitsVerified, setAttachmentLimitsVerified] = useState(false);
  const [profile, setProfile] = useState("");
  const [conversationTitle, setConversationTitle] = useState("");
  const [conversationStatus, setConversationStatus] = useState("");
  const [modelContext, setModelContext] = useState<ConversationModelContext | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [continuity, setContinuity] = useState("");
  const [retryFollow, setRetryFollow] = useState(false);
  const compactTaskDetails = useMediaQuery("(max-width: 1020px)");
  const [taskDetailsOpen, setTaskDetailsOpen] = useState(false);
  const taskDetailsTriggerRef = useRef<HTMLButtonElement>(null);
  const taskDetailsPanelRef = useRef<HTMLElement>(null);
  const controllersRef = useRef(new Set<AbortController>());
  const liveConversationRef = useRef<string | null>(null);
  const activeRunRef = useRef<string | null>(null);
  const followCursorRef = useRef(0);
  const live = useMemo(() => normalizeEvents(events), [events]);
  const lastAssistantMessageId = useMemo(
    () => [...messages].reverse().find(
      (message) => message.role === "assistant" && !message.superseded_by,
    )?.id,
    [messages],
  );

  useEffect(() => {
    setError("");
    setContinuity("");
    setRetryFollow(false);
    const priorLive = liveConversationRef.current;
    if (priorLive && priorLive !== conversationId) {
      abortStreams();
      activeRunRef.current = null;
      liveConversationRef.current = null;
      followCursorRef.current = 0;
      setEvents([]);
    }
    if (!conversationId) {
      setEvents([]);
      setMessages([]);
      setArtifacts([]);
      setArtifactCursor(null);
      setConversationTitle("");
      setConversationStatus("");
      setModelContext(null);
      return;
    }
    const ownsLiveStream = (
      liveConversationRef.current === conversationId
      && controllersRef.current.size > 0
    );
    if (!ownsLiveStream) {
      setEvents([]);
      followCursorRef.current = 0;
    }
    void loadConversation(conversationId)
      .then((thread) => {
        if (
          thread.active_run_id
          && !ownsLiveStream
          && controllersRef.current.size === 0
        ) {
          activeRunRef.current = thread.active_run_id;
          void reattach(conversationId, 0, true);
        }
      })
      .catch((reason) => setError(reasonText(reason)));
  }, [conversationId]);

  useEffect(() => () => abortStreams(), []);

  useEffect(() => {
    setTaskDetailsOpen(false);
  }, [conversationId]);

  useEffect(() => {
    if (!compactTaskDetails) {
      setTaskDetailsOpen(false);
      return;
    }
    if (!taskDetailsOpen) return;

    const panel = taskDetailsPanelRef.current;
    const priorOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.setTimeout(() => {
      panel?.querySelector<HTMLElement>("[data-task-details-close]")?.focus();
    }, 0);

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeTaskDetails();
        return;
      }
      if (event.key !== "Tab" || !panel) return;
      const focusable = focusableElements(panel);
      if (focusable.length === 0) {
        event.preventDefault();
        panel.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && (
        document.activeElement === first
        || !panel.contains(document.activeElement)
      )) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (
        document.activeElement === last
        || !panel.contains(document.activeElement)
      )) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = priorOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [compactTaskDetails, taskDetailsOpen]);

  useEffect(() => {
    void client.modelProfiles().then((result) => {
      setProfiles(result.profiles.filter((item) => item.available));
    }).catch(() => setProfiles([]));
    void client.chatConfig().then((result) => {
      setAttachmentLimits(result.attachments);
      setAttachmentLimitsVerified(true);
    }).catch(() => setAttachmentLimitsVerified(false));
  }, []);

  async function send(
    message: string,
    attachments: ChatAttachment[],
  ): Promise<boolean> {
    if (conversationId && conversationStatus !== "active") {
      setError(
        conversationStatus === "closed"
          ? "Restore this conversation before adding another turn."
          : "Wait for the conversation state to finish loading.",
      );
      return true;
    }
    setError("");
    setContinuity("");
    setRetryFollow(false);
    const joiningActiveTurn = controllersRef.current.size > 0;
    if (!joiningActiveTurn) {
      setEvents([]);
      followCursorRef.current = 0;
    }
    const controller = new AbortController();
    addController(controller);
    let sawStreamEvent = false;
    try {
      const queued = await client.streamChat({
        conversation_id: conversationId ?? undefined,
        message,
        attachments: attachments.length ? attachments : undefined,
        model_profile_id: profile || undefined,
        idempotency_key: crypto.randomUUID(),
        origin: "worker",
      }, (event) => {
        sawStreamEvent = true;
        acceptLiveEvent(event);
      }, controller.signal);
      if (queued) {
        activeRunRef.current = queued.run_id;
        liveConversationRef.current = queued.conversation_id;
        setContinuity("Instruction queued behind the active turn.");
      } else if (sawStreamEvent) {
        const id = liveConversationRef.current ?? conversationId;
        if (id) {
          await loadConversation(id);
          setEvents([]);
        }
        activeRunRef.current = null;
        liveConversationRef.current = null;
      }
      onChanged();
      return false;
    } catch (reason) {
      if (!controller.signal.aborted) {
        setError(reasonText(reason));
        if (liveConversationRef.current) {
          setContinuity("Live updates paused. The run is still governed server-side.");
          setRetryFollow(true);
        }
      }
      return reason instanceof BoltrigApiError && reason.status === 413;
    } finally {
      removeController(controller);
    }
  }

  async function stop() {
    const runId = activeRunRef.current ?? live.runId;
    abortStreams();
    if (runId) await client.cancelRun(runId);
    activeRunRef.current = null;
    liveConversationRef.current = null;
    setContinuity("");
    setRetryFollow(false);
    if (conversationId) {
      await loadConversation(conversationId);
      setEvents([]);
    }
  }

  async function loadConversation(id: string) {
    const [thread, artifactResult, list] = await Promise.all([
      client.conversation(id),
      client.artifacts({ conversationId: id, limit: 25 }).catch(() => ({
        artifacts: [] as Artifact[],
        next_cursor: null,
      })),
      client.conversations().catch(() => ({ conversations: [] })),
    ]);
    setMessages(thread.messages);
    setModelContext(thread.model_context ?? null);
    setArtifacts(artifactResult.artifacts);
    setArtifactCursor(artifactResult.next_cursor ?? null);
    const summary = list.conversations.find((conversation) => conversation.id === id);
    setConversationTitle(summary?.title ?? "Untitled task");
    setConversationStatus(summary?.status ?? "");
    return thread;
  }

  async function loadMoreArtifacts() {
    if (!conversationId || !artifactCursor || loadingArtifacts) return;
    setLoadingArtifacts(true);
    try {
      const result = await client.artifacts({
        conversationId,
        limit: 25,
        cursor: artifactCursor,
      });
      setArtifacts((current) => {
        const known = new Set(current.map((artifact) => artifact.id));
        return [
          ...current,
          ...result.artifacts.filter((artifact) => !known.has(artifact.id)),
        ];
      });
      setArtifactCursor(result.next_cursor ?? null);
    } catch (reason) {
      setError(reasonText(reason));
    } finally {
      setLoadingArtifacts(false);
    }
  }

  async function refreshArtifacts(id: string) {
    const result = await client.artifacts({ conversationId: id, limit: 25 });
    setArtifacts(result.artifacts);
    setArtifactCursor(result.next_cursor ?? null);
  }

  async function reattach(id: string, since: number, reset: boolean) {
    if (
      controllersRef.current.size > 0
      && liveConversationRef.current === id
    ) return;
    if (reset) setEvents([]);
    setError("");
    setRetryFollow(false);
    setContinuity("Reconnecting to the active turn…");
    liveConversationRef.current = id;
    const controller = new AbortController();
    let followNextRun = false;
    addController(controller);
    try {
      const result = await client.followConversation(id, (frame) => {
        followCursorRef.current = frame.cursor;
        if (frame.replay_truncated) {
          setContinuity(
            "Earlier live activity aged out of the bounded replay window. "
            + "The durable transcript will refresh when the turn settles.",
          );
        }
        acceptLiveEvent(frame.event);
      }, { since, signal: controller.signal });
      followCursorRef.current = result.cursor;
      if (result.status !== "aborted") {
        const thread = await loadConversation(id);
        setEvents([]);
        if (thread.active_run_id) {
          activeRunRef.current = thread.active_run_id;
          liveConversationRef.current = id;
          followCursorRef.current = 0;
          followNextRun = true;
        } else {
          activeRunRef.current = null;
          liveConversationRef.current = null;
          setContinuity("");
          onChanged();
        }
      }
    } catch (reason) {
      if (!controller.signal.aborted) {
        setError(reasonText(reason));
        setContinuity("Live updates paused. Reconnect to continue following this run.");
        setRetryFollow(true);
      }
    } finally {
      removeController(controller);
      if (followNextRun) void reattach(id, 0, true);
    }
  }

  function acceptLiveEvent(event: ChatEvent) {
    if (event.type === "steer_queued") {
      setContinuity("Instruction queued behind the active turn.");
    } else if (event.type === "steer_consumed") {
      setContinuity("Queued instruction is now running.");
    } else if (event.type === "artifact") {
      const id = liveConversationRef.current ?? conversationId;
      if (id) {
        void refreshArtifacts(id).catch(() => {
          setContinuity("An output is ready. Refresh the task if it is not listed yet.");
        });
      }
    } else if (event.type === "artifact_rejected") {
      setError(
        `${event.count} generated output${event.count === 1 ? "" : "s"} `
        + "did not satisfy the artifact safety contract.",
      );
    } else if (event.type === "event_unavailable") {
      setContinuity(
        "Some internal runtime activity was withheld from the public task stream.",
      );
    }
    if (event.type === "message_start") {
      const priorRun = activeRunRef.current;
      activeRunRef.current = event.run_id;
      liveConversationRef.current = event.conversation_id;
      if (priorRun && priorRun !== event.run_id) {
        setEvents([event]);
        void loadConversation(event.conversation_id).catch(() => undefined);
      } else {
        setEvents((current) => [...current, event]);
      }
      if (event.conversation_id !== conversationId) {
        onConversation(event.conversation_id);
      }
      return;
    }
    setEvents((current) => [...current, event]);
  }

  function addController(controller: AbortController) {
    controllersRef.current.add(controller);
    setLoading(true);
  }

  function removeController(controller: AbortController) {
    controllersRef.current.delete(controller);
    setLoading(controllersRef.current.size > 0);
  }

  function abortStreams() {
    for (const controller of controllersRef.current) controller.abort();
    controllersRef.current.clear();
    setLoading(false);
  }

  async function controlsChanged() {
    if (conversationId) await loadConversation(conversationId);
    onChanged();
  }

  function closeTaskDetails() {
    setTaskDetailsOpen(false);
    window.setTimeout(() => taskDetailsTriggerRef.current?.focus(), 0);
  }

  return (
    <div className="chat-layout">
      <main className="chat-main">
        <header className="chat-header">
          <div className="agent-heading">
            <Familiar state={loading ? "working" : "ready"} />
            <div>
              <p className="eyebrow">Boltrig activity</p>
              <h1>{
                conversationStatus === "closed"
                  ? "Closed conversation"
                  : conversationId
                    ? "Continue the work"
                    : "What should we get done?"
              }</h1>
            </div>
          </div>
          <div className="chat-header-actions">
            {(!conversationId || conversationStatus === "active") && (
              <VoiceCall
                conversationId={conversationId}
                modelProfileId={profile || undefined}
                onConversation={onConversation}
                onError={setError}
              />
            )}
            {compactTaskDetails && (
              <button
                aria-controls="worker-task-details"
                aria-expanded={taskDetailsOpen}
                className="secondary-button task-details-trigger"
                onClick={() => setTaskDetailsOpen(true)}
                ref={taskDetailsTriggerRef}
                type="button"
              >
                Task details
              </button>
            )}
          </div>
        </header>
        <div className="transcript" aria-live="polite">
          {messages.length === 0 && events.length === 0 ? <Welcome /> : null}
          {messages.map((message) => <Message key={message.id} message={message} />)}
          {modelContext?.compacted && (
            <details className="notice model-context-notice">
              <summary>
                Model context uses a summary of {modelContext.covered_count} earlier
                messages plus {modelContext.recent_exact_count} recent messages verbatim.
              </summary>
              <p>
                The complete transcript remains visible here. The next model turn
                receives this derived summary for the older portion:
              </p>
              <blockquote>{modelContext.summary}</blockquote>
            </details>
          )}
          {events.length > 0 && <LiveTurn turn={live} />}
          {continuity && (
            <p className="notice" role="status">
              {continuity}
              {retryFollow && conversationId && (
                <>{" "}<button
                  type="button"
                  className="secondary-button"
                  onClick={() => void reattach(
                    conversationId,
                    followCursorRef.current,
                    followCursorRef.current === 0,
                  )}
                >Reconnect</button></>
              )}
            </p>
          )}
          {error && <p className="notice" role="alert">{error}</p>}
        </div>
        <Composer
          busy={loading}
          disabled={Boolean(conversationId) && conversationStatus !== "active"}
          closed={conversationStatus === "closed"}
          profiles={profiles}
          profile={profile}
          attachmentLimits={attachmentLimits}
          attachmentLimitsVerified={attachmentLimitsVerified}
          onProfile={setProfile}
          onSend={send}
          onStop={stop}
        />
      </main>
      {compactTaskDetails && taskDetailsOpen && (
        <button
          aria-label="Dismiss task details"
          className="task-details-scrim"
          onClick={closeTaskDetails}
          type="button"
        />
      )}
      <RightRail
        artifacts={artifacts}
        turn={live}
        conversation={conversationId && conversationStatus ? {
          id: conversationId,
          title: conversationTitle || "Untitled task",
          status: conversationStatus,
          lastAssistantMessageId,
        } : null}
        artifactCursor={artifactCursor}
        loadingArtifacts={loadingArtifacts}
        onLoadMoreArtifacts={loadMoreArtifacts}
        onConversationChanged={controlsChanged}
        compact={compactTaskDetails}
        open={!compactTaskDetails || taskDetailsOpen}
        panelRef={taskDetailsPanelRef}
        onClose={closeTaskDetails}
        onConversationDeleted={() => {
          closeTaskDetails();
          void controlsChanged().catch((reason) => setError(reasonText(reason)));
        }}
      />
    </div>
  );
}

function Welcome() {
  return (
    <section className="welcome">
      <div className="welcome-mark" aria-hidden>ϟ</div>
      <h2>Bring me a task, not a prompt.</h2>
      <p>I can plan the work, use the tools your workspace grants, pause for approval, and return the artifact here.</p>
      <div className="suggestions">
        <span>Turn these notes into a brief</span>
        <span>Research and compare options</span>
        <span>Prepare this week’s update</span>
      </div>
    </section>
  );
}

function Message({ message }: { message: ChatMessage }) {
  const turn = useMemo(() => normalizeEvents(message.events ?? []), [message.events]);
  const identity = turn.subagents[0];
  return (
    <article className={`message ${message.role}`}>
      <div className="message-author">
        {message.role === "assistant" ? (
          <Familiar
            state={turn.ended ? "ready" : "working"}
            genotype={identity?.familiarGenotype}
            label={identity?.name}
          />
        ) : <span className="user-avatar">Y</span>}
        <strong>{message.role === "assistant" ? identity?.name ?? "Boltrig" : "You"}</strong>
      </div>
      <div className="message-content">
        {turn.degraded && (
          <p className="notice" role="status">
            This response used a degraded fallback; treat its result as incomplete.
          </p>
        )}
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
        {message.attachments?.map((item) => (
          <button
            type="button"
            className="attachment"
            key={item.name}
            onClick={() => downloadAttachment(item)}
          >
            ▧ {item.name}{item.size != null ? ` · ${formatBytes(item.size)}` : ""}
          </button>
        ))}
        {message.events?.length ? <TurnActivity turn={turn} /> : null}
      </div>
    </article>
  );
}

function LiveTurn({ turn }: { turn: NormalizedTurn }) {
  const identity = turn.subagents[0];
  return (
    <article className="message assistant live">
      <div className="message-author">
        <Familiar
          state={turn.ended ? "ready" : "working"}
          genotype={identity?.familiarGenotype}
          label={identity?.name}
        />
        <strong>{identity?.name ?? "Boltrig"}</strong>
      </div>
      <div className="message-content">
        {turn.degraded && (
          <p className="notice" role="status">
            This response used a degraded fallback; treat its result as incomplete.
          </p>
        )}
        {turn.reasoning && <details><summary>Working notes</summary><p>{turn.reasoning}</p></details>}
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{turn.text || "Working…"}</ReactMarkdown>
        <TurnActivity turn={turn} />
        {turn.modelRouting && (
          <p className="routing-note">
            {turn.modelRouting.selectedProfileId} · {turn.modelRouting.routingClass}
            {turn.modelRouting.overridden ? " · policy adjusted" : ""}
          </p>
        )}
      </div>
    </article>
  );
}

function TurnActivity({ turn }: { turn: NormalizedTurn }) {
  if (!turn.timeline.length) return null;
  return (
    <div className="activity">
      {turn.timeline.map((item) => {
        if (item.kind === "tool") return (
          <div className="activity-row" key={item.key}>
            <span className={`activity-dot ${item.entry.status}`} />
            <span>{item.entry.verb}</span><small>{item.entry.status}</small>
          </div>
        );
        if (item.kind === "subagent") {
          const hasIdentity = (
            item.entry.familiarGenotype?.source === "agent_capability.name.v1"
          );
          return (
            <div className="activity-row subagent" key={item.key}>
              <span
                className="mini-familiar"
                data-genotype-source={hasIdentity
                  ? item.entry.familiarGenotype?.source
                  : "unbound"}
                style={hasIdentity
                  ? familiarPalette(item.entry.familiarGenotype?.palette)
                  : undefined}
                aria-label={hasIdentity
                  ? `${item.entry.name ?? "Subagent"} profile Familiar`
                  : `${item.entry.name ?? "Subagent"} activity`}
              /><span>
                {item.entry.name ?? "Subagent"} · {item.entry.task}
                {item.entry.spawnRule ? ` · policy ${item.entry.spawnRule.id}` : ""}
              </span>
              <small>{item.entry.status ?? "running"}</small>
            </div>
          );
        }
        if (item.kind === "hitl") return (
          <div className="approval-card" key={item.key}>
            <strong>Approval needed</strong><p>{item.entry.question}</p>
          </div>
        );
        if (item.kind === "question") return (
          <LiveQuestionCard question={item.entry} key={item.key} />
        );
        return null;
      })}
    </div>
  );
}

function Familiar({
  state,
  genotype,
  label,
}: {
  state: "ready" | "working";
  genotype?: FamiliarGenotype | null;
  label?: string;
}) {
  const hasIdentity = genotype?.source === "agent_capability.name.v1";
  return (
    <span
      className={`familiar-orb ${state}`}
      data-genotype-source={hasIdentity ? genotype.source : "unbound"}
      role="img"
      aria-label={hasIdentity
        ? `${label ?? "Agent"} Familiar · ${state}`
        : `Boltrig activity · ${state}`}
      style={hasIdentity ? familiarPalette(genotype.palette) : undefined}
    ><i /></span>
  );
}

function familiarPalette(palette?: string[] | null): React.CSSProperties {
  const colors = [...(palette ?? [])]
    .filter((value) => /^#[0-9a-f]{6}$/i.test(value))
    .slice(0, 3);
  if (colors.length !== 3) return {};
  return { background: `radial-gradient(circle at 35% 30%, ${colors.join(", ")})` };
}

interface ComposerProps {
  busy: boolean;
  disabled: boolean;
  closed: boolean;
  profiles: ModelProfile[];
  profile: string;
  attachmentLimits: ChatAttachmentLimits;
  attachmentLimitsVerified: boolean;
  onProfile(value: string): void;
  onSend(message: string, files: ChatAttachment[]): Promise<boolean>;
  onStop(): Promise<void>;
}

function Composer({
  busy,
  disabled,
  closed,
  profiles,
  profile,
  attachmentLimits,
  attachmentLimitsVerified,
  onProfile,
  onSend,
  onStop,
}: ComposerProps) {
  const [value, setValue] = useState("");
  const [files, setFiles] = useState<ChatAttachment[]>([]);
  const [fileError, setFileError] = useState("");
  const input = useRef<HTMLInputElement>(null);

  async function addFiles(list: FileList | null) {
    if (!list) return;
    setFileError("");
    const selected = Array.from(list);
    if (files.length + selected.length > attachmentLimits.max_count) {
      setFileError(`Attach at most ${attachmentLimits.max_count} files to one turn.`);
      return;
    }
    const tooLarge = selected.find((file) => file.size > attachmentLimits.max_bytes);
    if (tooLarge) {
      setFileError(
        `${tooLarge.name} is too large. Each file must be ${formatBytes(attachmentLimits.max_bytes)} or smaller.`,
      );
      return;
    }
    const total = files.reduce((sum, file) => sum + (file.size ?? 0), 0)
      + selected.reduce((sum, file) => sum + file.size, 0);
    if (total > attachmentLimits.max_total_bytes) {
      setFileError(
        `Attachments must total ${formatBytes(attachmentLimits.max_total_bytes)} or less.`,
      );
      return;
    }
    const added = await Promise.all(selected.map(async (file) => ({
      name: file.name,
      media_type: file.type || "application/octet-stream",
      data: arrayBufferToBase64(await file.arrayBuffer()),
      size: file.size,
    })));
    setFiles((current) => [...current, ...added]);
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const message = value.trim();
    if (!message) return;
    setValue("");
    const sentFiles = files;
    setFiles([]);
    const restore = await onSend(message, sentFiles);
    if (restore) {
      setValue((current) => current || message);
      setFiles((current) => current.length ? current : sentFiles);
    }
  }

  return (
    <form className={`composer${closed ? " closed" : ""}`} onSubmit={submit}>
      {closed && (
        <p className="composer-closed" role="status">
          Restore this conversation to continue it.
        </p>
      )}
      {files.length > 0 && <div className="file-row">{files.map((file, index) => (
        <button type="button" className="file-chip" key={`${file.name}-${index}`} onClick={() => setFiles((items) => items.filter((item) => item !== file))}>▧ {file.name} · {modelReadable(file.media_type, attachmentLimits.model_readable_media_types) ? "model-readable" : "record only"} ×</button>
      ))}</div>}
      {fileError && <p className="notice" role="alert">{fileError}</p>}
      <textarea
        aria-label="Task instructions"
        placeholder={
          closed
            ? "This conversation is closed"
            : disabled
              ? "Loading conversation state…"
              : "Describe what you want done…"
        }
        disabled={disabled}
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.nativeEvent.isComposing || event.keyCode === 229) return;
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            event.currentTarget.form?.requestSubmit();
          }
        }}
      />
      <div className="composer-tools">
        <div>
          <input ref={input} hidden type="file" multiple onChange={(event) => void addFiles(event.target.files)} />
          <button type="button" className="icon-button" disabled={disabled} onClick={() => input.current?.click()} aria-label="Attach files">＋</button>
          {profiles.length > 0 && (
            <select aria-label="Model profile" disabled={disabled} value={profile} onChange={(event) => onProfile(event.target.value)}>
              <option value="">Automatic routing</option>
              {profiles.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>
          )}
        </div>
        <div>
          {busy && (
            <button className="stop-button" type="button" onClick={() => void onStop()}>
              ■ Stop
            </button>
          )}
          <button className="send-button" type="submit" disabled={disabled || !value.trim()}>
            {busy ? "Queue next ↑" : "Send ↑"}
          </button>
        </div>
      </div>
      <p className="muted small">
        Text files are included in the model task. Other file types are recorded
        with the conversation but are not read by the model.
        {!attachmentLimitsVerified && " Server limits will be checked when you send."}
      </p>
    </form>
  );
}

interface RightRailProps {
  artifacts: Artifact[];
  artifactCursor: string | null;
  loadingArtifacts: boolean;
  compact: boolean;
  open: boolean;
  panelRef: RefObject<HTMLElement>;
  turn: NormalizedTurn;
  conversation: {
    id: string;
    title: string;
    status: string;
    lastAssistantMessageId?: string;
  } | null;
  onLoadMoreArtifacts(): Promise<void>;
  onConversationChanged(): Promise<void>;
  onConversationDeleted(): void;
  onClose(): void;
}

function RightRail({
  artifacts,
  artifactCursor,
  loadingArtifacts,
  compact,
  open,
  panelRef,
  turn,
  conversation,
  onLoadMoreArtifacts,
  onConversationChanged,
  onConversationDeleted,
  onClose,
}: RightRailProps) {
  const [downloadError, setDownloadError] = useState("");
  const [materialized, setMaterialized] = useState<Record<string, string>>({});

  async function download(artifact: Artifact) {
    setDownloadError("");
    try {
      const bytes = await client.downloadArtifact(artifact.id);
      const result = await materializeArtifact(artifact.name, bytes);
      if (result.status === "saved") {
        setMaterialized((current) => ({
          ...current,
          [artifact.id]: result.handle,
        }));
      } else if (result.status === "web_fallback") {
        const url = URL.createObjectURL(new Blob([bytes], { type: artifact.media_type }));
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = artifact.name;
        anchor.click();
        URL.revokeObjectURL(url);
      }
    } catch {
      setDownloadError("The artifact could not be downloaded. It is safe to retry.");
    }
  }

  async function useMaterialized(
    artifact: Artifact,
    action: (handle: string) => Promise<void>,
  ) {
    const handle = materialized[artifact.id];
    if (!handle) return;
    setDownloadError("");
    try {
      await action(handle);
    } catch {
      setDownloadError(
        `The saved copy of ${artifact.name} is no longer available. Save it again.`,
      );
      setMaterialized((current) => {
        const next = { ...current };
        delete next[artifact.id];
        return next;
      });
    }
  }
  return (
    <aside
      aria-hidden={compact && !open}
      aria-label={compact ? undefined : "Task details"}
      aria-labelledby={compact ? "worker-task-details-title" : undefined}
      aria-modal={compact ? true : undefined}
      className={`right-rail${compact ? " task-details-sheet" : ""}${open ? " open" : ""}`}
      id="worker-task-details"
      ref={panelRef}
      role={compact ? "dialog" : undefined}
      tabIndex={compact ? -1 : undefined}
      {...(compact && !open ? { inert: "" } : {})}
    >
      {compact && (
        <div className="task-details-header">
          <div>
            <p className="eyebrow">Current task</p>
            <h2 id="worker-task-details-title">Task details</h2>
          </div>
          <button
            aria-label="Close task details"
            className="icon-button"
            data-task-details-close
            onClick={onClose}
            type="button"
          >
            ×
          </button>
        </div>
      )}
      <section>
        <p className="eyebrow">Artifacts</p>
        {artifacts.length === 0 ? <p className="muted small">Outputs from this task will appear here.</p> : artifacts.map((item) => {
          const handle = materialized[item.id];
          return (
            <div className="artifact-card" key={item.id}>
              <button
                className="artifact-download"
                onClick={() => void download(item)}
                type="button"
              >
                <span className="artifact-icon">▧</span>
                <span><strong>{item.name}</strong><small>{item.media_type} · rev {item.revision}</small></span>
              </button>
              {handle && (
                <span className="artifact-native-actions">
                  <button
                    className="secondary-button"
                    onClick={() => void useMaterialized(item, openMaterializedArtifact)}
                    type="button"
                  >Open</button>
                  <button
                    className="secondary-button"
                    onClick={() => void useMaterialized(item, revealMaterializedArtifact)}
                    type="button"
                  >Reveal</button>
                </span>
              )}
            </div>
          );
        })}
        {artifactCursor && (
          <button
            className="secondary-button"
            type="button"
            disabled={loadingArtifacts}
            onClick={() => void onLoadMoreArtifacts()}
          >
            {loadingArtifacts ? "Loading…" : "Load more artifacts"}
          </button>
        )}
        {downloadError && <p className="notice" role="alert">{downloadError}</p>}
      </section>
      <section>
        <p className="eyebrow">Activity</p>
        <dl className="run-facts">
          <div><dt>Run</dt><dd>{turn.runId?.slice(0, 10) ?? "—"}</dd></div>
          <div><dt>Tools</dt><dd>{turn.tools.length}</dd></div>
          <div><dt>Delegations</dt><dd>{turn.subagents.length}</dd></div>
          <div><dt>Status</dt><dd>{turn.cancelled ? "Cancelled" : turn.ended ? "Done" : turn.runId ? "Running" : "Ready"}</dd></div>
        </dl>
      </section>
      {conversation && (
        <ConversationControls
          conversationId={conversation.id}
          title={conversation.title}
          status={conversation.status}
          lastAssistantMessageId={conversation.lastAssistantMessageId}
          onChanged={() => void onConversationChanged()}
          onDeleted={onConversationDeleted}
        />
      )}
      <section className="privacy-note">
        <span aria-hidden>◇</span>
        <p><strong>Governed by Boltrig</strong>Tools, credentials, memory, and approvals stay server-side.</p>
      </section>
    </aside>
  );
}

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary);
}

function downloadAttachment(attachment: ChatAttachment) {
  try {
    const raw = atob(attachment.data);
    const bytes = Uint8Array.from(raw, (character) => character.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], {
      type: attachment.media_type || "application/octet-stream",
    }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = attachment.name || "attachment";
    anchor.click();
    URL.revokeObjectURL(url);
  } catch {
    // Persisted metadata can outlive an unavailable/corrupt inline payload.
    // The message remains readable; never navigate to attacker-controlled data.
  }
}

function formatBytes(value: number): string {
  if (value < 1_024) return `${value} B`;
  if (value < 1_048_576) return `${Math.ceil(value / 1_024)} KB`;
  return `${(value / 1_048_576).toFixed(1)} MB`;
}

function modelReadable(mediaType: string, patterns: string[]): boolean {
  const normalized = mediaType.toLowerCase();
  return patterns.some((pattern) => (
    pattern.endsWith("/*")
      ? normalized.startsWith(pattern.slice(0, -1).toLowerCase())
      : normalized === pattern.toLowerCase()
  ));
}

function reasonText(reason: unknown): string {
  if (reason instanceof BoltrigApiError) {
    if (reason.status === 401) return "Sign in to Boltrig to continue.";
    if (reason.status === 403) return "This workspace does not grant that action.";
    if (reason.status === 413) {
      return "The server rejected the attachment limits. Your task draft has been restored.";
    }
    if (reason.status === 503) return "This capability is unavailable right now.";
  }
  return reason instanceof Error ? reason.message : "Something went wrong.";
}

function useMediaQuery(query: string): boolean {
  const matches = () => (
    typeof window !== "undefined"
    && typeof window.matchMedia === "function"
    && window.matchMedia(query).matches
  );
  const [matched, setMatched] = useState(matches);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(query);
    const onChange = (event: MediaQueryListEvent) => setMatched(event.matches);
    setMatched(media.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [query]);

  return matched;
}

function focusableElements(container: HTMLElement): HTMLElement[] {
  return [...container.querySelectorAll<HTMLElement>(
    "a[href], button:not([disabled]), input:not([disabled]), "
    + "select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])",
  )].filter((element) => element.getAttribute("aria-hidden") !== "true");
}
