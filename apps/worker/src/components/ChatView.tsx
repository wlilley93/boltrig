import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from "react";
import { flushSync } from "react-dom";
import {
  BoltrigApiError,
  normalizeEvents,
  type Artifact,
  type ChatAttachment,
  type ChatAttachmentLimits,
  type ChatEvent,
  type ChatMessage,
  type ConversationModelContext,
  type FamiliarPhenotypeResponse,
  type IntegrationCatalogueEntry,
  type ModelProfile,
  type NormalizedTurn,
  type SubagentEntry,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import { useMediaQuery } from "../useMediaQuery";
import { navigate } from "../routes";
import {
  materializeArtifact,
  openMaterializedArtifact,
  revealMaterializedArtifact,
} from "../desktop";
import { appliedTheme, toggleTheme } from "../theme";
import { FamiliarBadge } from "./familiar/FamiliarBadge";
import { FamiliarStage } from "./familiar/FamiliarStage";
import { StageBody, type StageTurnInput } from "./StageBody";
import {
  familiarStateFromTurn,
  type FamiliarPresentationMode,
} from "./familiar/FamiliarState";
import { LiveQuestionCard } from "./LiveQuestionCard";
import { MobileChat } from "./MobileChat";
import { ConversationControls } from "./ConversationControls";
import { VoiceCall } from "./VoiceCall";
import { InlineApproval, SettledApproval } from "./chat/InlineApproval";
import { ModelChip } from "./chat/ModelChip";
import { OrderedWorkTranscript } from "./chat/OrderedWorkTranscript";
import { RunSectionView } from "./chat/RunSectionView";
import { SubagentChips } from "./chat/SubagentChips";
import { SubagentTabs } from "./chat/SubagentTabs";
import { integrationsUsedByConversation } from "./chat/toolActivity";
import { useTechDetails } from "./chat/useTechDetails";
import "./chat/chat.css";
import "./chat/ChatHeaderParity.css";
import "./chat/ChatRailParity.css";
import "./chat/ChatViewParity.css";

interface ChatViewProps {
  conversationId: string | null;
  onConversation(id: string): void;
  onChanged(): void;
  /** Reports the server-owned active-run state to the shell rail. */
  onWorkingChange?(conversationId: string, working: boolean): void;
  /** Mount point for the subagent tab strip (SubagentTabs): subagent chips
      and fan-out rows call this with the subagent whose pane should open
      beside the conversation. Until the tabs surface is wired, the rows stay
      non-interactive rather than pretending a pane exists. */
  onOpenSubagent?(agent: SubagentEntry): void;
}

type ConversationLoadState = {
  conversationId: string | null;
  phase: "idle" | "loading" | "ready" | "error";
  error: string;
};

const DEFAULT_ATTACHMENT_LIMITS: ChatAttachmentLimits = {
  max_count: 8,
  max_bytes: 256 * 1_024,
  max_total_bytes: 1_024 * 1_024,
  model_readable_media_types: ["text/*"],
};

function readVoiceBannerPreference(): boolean {
  try {
    return localStorage.getItem("boltrig-worker-voice-banner-dismissed") !== "true";
  } catch {
    return true;
  }
}

export function ChatView({
  conversationId,
  onConversation,
  onChanged,
  onWorkingChange,
  onOpenSubagent,
}: ChatViewProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [events, setEvents] = useState<ChatEvent[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [artifactCursor, setArtifactCursor] = useState<string | null>(null);
  const [loadingArtifacts, setLoadingArtifacts] = useState(false);
  const [profiles, setProfiles] = useState<ModelProfile[]>([]);
  const [attachmentLimits, setAttachmentLimits] = useState(DEFAULT_ATTACHMENT_LIMITS);
  const [profile, setProfile] = useState("");
  const [conversationTitle, setConversationTitle] = useState("");
  const [conversationStatus, setConversationStatus] = useState("");
  const [modelContext, setModelContext] = useState<ConversationModelContext | null>(null);
  const [conversationLoad, setConversationLoad] = useState<ConversationLoadState>(() => (
    conversationId
      ? { conversationId, phase: "loading", error: "" }
      : { conversationId: null, phase: "idle", error: "" }
  ));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [continuity, setContinuity] = useState("");
  const [retryFollow, setRetryFollow] = useState(false);
  const compactTaskDetails = useMediaQuery("(max-width: 1020px)");
  // Mobile is a different surface, not the console squeezed. Below the phone
  // breakpoint the conversation is drawn by MobileChat on its own palette.
  const phone = useMediaQuery("(max-width: 640px)");
  // The split panes (subagent tabs, run-section drawing) mount only in the
  // desktop layout. Narrower widths keep chips and rail rows as static
  // readings, so no control is offered whose target surface cannot appear.
  const canOpenPanes = !phone && !compactTaskDetails;
  // The composer draft is lifted so starter cards can fill it (the design's
  // New screen behaviour: a starter fills the draft, it never sends).
  const [draft, setDraft] = useState("");
  const [voiceBanner, setVoiceBanner] = useState(readVoiceBannerPreference);
  // Queued steers are durable user messages with no run id yet. Keep a small
  // local echo so the row appears as soon as the 202 receipt arrives; the next
  // conversation load reconciles it with the append-only message log.
  const [localQueuedMessages, setLocalQueuedMessages] = useState<ChatMessage[]>([]);
  const [consumedSteerIds, setConsumedSteerIds] = useState<string[]>([]);
  // Desktop-only rail visibility. Compact widths keep the task-details sheet
  // and its single trigger untouched (the 39c14bd invariant).
  const [railOpen, setRailOpen] = useState(true);
  // Subagent tabs hold a runId-tagged snapshot of the entries they were opened
  // for. Tab keys are per-turn event indices, so a key minted by one turn must
  // never resolve against another turn's entries; the tag stops the next turn's
  // identical index from stealing a tab, and the snapshot keeps a settled
  // turn's tabs readable instead of vanishing mid-read.
  const [openTabs, setOpenTabs] = useState<Array<{ key: string; agent: SubagentEntry }>>([]);
  const [tabsRunId, setTabsRunId] = useState<string | null>(null);
  const [activeSubagentKey, setActiveSubagentKey] = useState<string | null>(null);
  // The run the section drawing was opened for — pinned, so a settling turn
  // neither yanks the reader out nor re-arms the drawing for the next run.
  const [sectionRunId, setSectionRunId] = useState<string | null>(null);
  // Turn durations measured while this client watched the run. ChatEvent
  // frames carry no timestamps, so a turn that was not watched here has no
  // duration to state - the work disclosure then omits the number.
  const [turnDurations, setTurnDurations] = useState<Record<string, number>>({});
  const liveStartsRef = useRef(new Map<string, number>());
  const draftInputRef = useRef<HTMLTextAreaElement>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const followTranscriptRef = useRef(true);
  const voiceDockRef = useRef<HTMLSpanElement>(null);
  const tech = useTechDetails();
  const [voiceActivity, setVoiceActivity] = useState<{
    speaking: boolean;
    level: number;
    bands?: number[];
    onset?: number;
  }>({ speaking: false, level: 0 });
  const [callActive, setCallActive] = useState(false);
  const [phenotype, setPhenotype] = useState<FamiliarPhenotypeResponse | null>(null);
  const [pageHidden, setPageHidden] = useState(
    typeof document !== "undefined" && document.visibilityState === "hidden",
  );
  const [taskDetailsOpen, setTaskDetailsOpen] = useState(false);
  const taskDetailsTriggerRef = useRef<HTMLButtonElement>(null);
  const taskDetailsPanelRef = useRef<HTMLElement>(null);
  const controllersRef = useRef(new Set<AbortController>());
  // Async chat work is authoritative only for the route generation that
  // started it. A controller alone is insufficient: the SDK intentionally
  // resolves an aborted SSE send with `undefined`, which otherwise looks like
  // an ordinarily completed stream after the reader has moved to another
  // conversation.
  const conversationGenerationRef = useRef(0);
  const selectedConversationRef = useRef<string | null>(conversationId);
  selectedConversationRef.current = conversationId;
  const liveConversationRef = useRef<string | null>(null);
  const activeRunRef = useRef<string | null>(null);
  const followCursorRef = useRef(0);
  const live = useMemo(() => normalizeEvents(events), [events]);
  const visibleMessages = useMemo(
    () => messages.filter((message) => !message.superseded_by),
    [messages],
  );
  const durableRailTurn = useMemo(() => {
    const latest = [...visibleMessages].reverse().find((message) => (
      message.role === "assistant"
      && ((message.events?.length ?? 0) > 0 || Boolean(message.run_id))
    ));
    const turn = normalizeEvents(latest?.events ?? []);
    if (!latest?.run_id) return turn;

    // Persisted assistant messages are written only after their streamed turn
    // completes. The store deliberately keeps message_start/message_end out of
    // `events`, with the authoritative run id beside them on the message. Carry
    // that boundary into the rail projection without minting synthetic events
    // or adding anything to the turn's activity timeline.
    return {
      ...turn,
      runId: turn.runId ?? latest.run_id,
      ended: true,
    };
  }, [visibleMessages]);
  // A live relay is authoritative while it has identified its run. Between
  // turns the compact rail reads the latest durable event receipt instead of
  // going blank or inventing entries to resemble the screenshot.
  const railTurn = live.runId ? live : durableRailTurn;
  const railTurnIsLive = Boolean(live.runId && live.runId === railTurn.runId && !live.ended);
  const lastAssistantMessageId = useMemo(
    () => [...visibleMessages].reverse().find((message) => (
      message.role === "assistant"
    ))?.id,
    [visibleMessages],
  );
  const queuedMessages = useMemo(() => {
    const assistantCount = visibleMessages.filter((message) => message.role === "assistant").length;
    const serverQueued = visibleMessages
      .filter((message) => message.role === "user")
      .slice(assistantCount)
      .filter((message) => (
        !message.run_id && !consumedSteerIds.includes(message.id)
      ));
    const byId = new Map<string, ChatMessage>();
    for (const message of [...serverQueued, ...localQueuedMessages]) byId.set(message.id, message);
    return [...byId.values()];
  }, [consumedSteerIds, localQueuedMessages, visibleMessages]);
  const queuedMessageIds = useMemo(
    () => new Set(queuedMessages.map((message) => message.id)),
    [queuedMessages],
  );
  const transcriptMessages = useMemo(
    () => visibleMessages.filter((message) => !queuedMessageIds.has(message.id)),
    [queuedMessageIds, visibleMessages],
  );
  const sources = useMemo(() => {
    const seen = new Set<string>();
    const result: ChatAttachment[] = [];
    for (const message of [...visibleMessages, ...localQueuedMessages]) {
      for (const attachment of message.attachments ?? []) {
        // The attachment contract has no durable id or digest. Payload bytes
        // are the only available discriminator for same-name revisions; using
        // metadata alone silently hid a later, distinct source from the rail.
        const key = attachmentIdentity(attachment);
        if (seen.has(key)) continue;
        seen.add(key);
        result.push(attachment);
      }
    }
    return result;
  }, [localQueuedMessages, visibleMessages]);
  const integrationSources = useMemo(
    () => integrationsUsedByConversation(visibleMessages, live.tools),
    [live.tools, visibleMessages],
  );
  const loadingConversation = Boolean(
    conversationId
    && (
      conversationLoad.conversationId !== conversationId
      || conversationLoad.phase === "loading"
    ),
  );
  const conversationLoadError = (
    conversationId
    && conversationLoad.conversationId === conversationId
    && conversationLoad.phase === "error"
  ) ? conversationLoad.error : "";
  const conversationReady = !conversationId || (
    conversationLoad.conversationId === conversationId
    && conversationLoad.phase === "ready"
  );

  // A route change is a hard data boundary. Layout timing matters here: a
  // normal effect permits one painted frame of the previous conversation under
  // the new route. Reset every conversation-owned projection before paint,
  // while preserving an in-flight stream whose message_start just assigned
  // its new conversation id.
  useLayoutEffect(() => {
    const ownsLiveStream = Boolean(
      conversationId
      && liveConversationRef.current === conversationId
      && controllersRef.current.size > 0
    );

    // A stream-created conversation adopts the already-open stream instead of
    // invalidating it when its new id reaches the hash. Every other selection
    // change is a hard generation boundary for sends, follows and stops.
    if (!ownsLiveStream) conversationGenerationRef.current += 1;

    setError("");
    setContinuity("");
    setRetryFollow(false);
    // The design's New tab resets the draft on entry; switching conversations
    // likewise drops a stale draft rather than carrying it across tasks.
    setDraft("");
    setLocalQueuedMessages([]);
    setConsumedSteerIds([]);
    setMessages([]);
    setArtifacts([]);
    setArtifactCursor(null);
    setLoadingArtifacts(false);
    setConversationTitle("");
    setConversationStatus("");
    setModelContext(null);
    followTranscriptRef.current = true;
    const priorLive = liveConversationRef.current;
    if (!ownsLiveStream && (
      controllersRef.current.size > 0
      || (priorLive && priorLive !== conversationId)
    )) {
      abortStreams();
    }
    if (!ownsLiveStream) {
      activeRunRef.current = null;
      liveConversationRef.current = null;
      followCursorRef.current = 0;
      setEvents([]);
      setTurnDurations({});
      liveStartsRef.current.clear();
    }
    if (!conversationId) {
      setConversationLoad({ conversationId: null, phase: "idle", error: "" });
      return;
    }
    setConversationLoad({ conversationId, phase: "loading", error: "" });
    void hydrateConversation(conversationId, ownsLiveStream);
  }, [conversationId]);

  useEffect(() => () => abortStreams(), []);

  useEffect(() => {
    setTaskDetailsOpen(false);
    setOpenTabs([]);
    setTabsRunId(null);
    setActiveSubagentKey(null);
    setSectionRunId(null);
  }, [conversationId]);

  // Open a task at its latest turn and follow new frames only while the reader
  // remains near the bottom. Scrolling up is an explicit reading choice; live
  // activity must never yank the transcript away from it.
  useLayoutEffect(() => {
    const transcript = transcriptRef.current;
    if (transcript && followTranscriptRef.current) {
      transcript.scrollTop = transcript.scrollHeight;
    }
  }, [
    conversationId,
    continuity,
    error,
    events.length,
    live.text,
    live.timeline.length,
    queuedMessages.length,
    transcriptMessages,
  ]);

  // Opening a subagent surfaces its own thread as a tab beside the transcript.
  // Only the live turn wires this: a settled turn's chips are static marks,
  // because their entries no longer exist to open. The optional onOpenSubagent
  // prop still fires so hosts and tests observe it.
  function openSubagentTab(agent: SubagentEntry) {
    onOpenSubagent?.(agent);
    if (!live.runId) return;
    if (tabsRunId !== live.runId) {
      // A new turn's first open replaces the old turn's tabs wholesale — the
      // old keys' index space is dead and must not linger next to new entries.
      setTabsRunId(live.runId);
      setOpenTabs([{ key: agent.key, agent }]);
    } else {
      setOpenTabs((tabs) => (tabs.some((tab) => tab.key === agent.key)
        ? tabs
        : [...tabs, { key: agent.key, agent }]));
    }
    setActiveSubagentKey(agent.key);
  }

  function closeSubagentTab(key: string) {
    const next = openTabs.filter((tab) => tab.key !== key);
    setOpenTabs(next);
    if (activeSubagentKey === key) setActiveSubagentKey(next[next.length - 1]?.key ?? null);
    // The pane unmounts with the last tab; hand focus back to the composer
    // rather than dropping it on <body>.
    if (next.length === 0) draftInputRef.current?.focus();
  }

  function closeAllSubagentTabs() {
    setOpenTabs([]);
    setActiveSubagentKey(null);
    draftInputRef.current?.focus();
  }

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
  }, [compactTaskDetails, phone, taskDetailsOpen]);

  // Cosmetic phenotype poll (A3): ~0.3Hz, paused while hidden; any failure
  // simply rests the being. The visual layer never gains a second event stream.
  useEffect(() => {
    if (pageHidden) return;
    let cancelled = false;
    const pull = () => {
      if (typeof client.familiarPhenotype !== "function") return;
      void client.familiarPhenotype()
        .then((result) => { if (!cancelled) setPhenotype(result); })
        .catch(() => { if (!cancelled) setPhenotype(null); });
    };
    pull();
    const timer = window.setInterval(pull, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [pageHidden]);

  useEffect(() => {
    const onVisibility = () => setPageHidden(document.visibilityState === "hidden");
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  useEffect(() => {
    void client.modelProfiles().then((result) => {
      setProfiles(result.profiles.filter((item) => item.available));
    }).catch(() => setProfiles([]));
    void client.chatConfig().then((result) => {
      setAttachmentLimits(result.attachments);
    }).catch(() => undefined);
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
    const generation = conversationGenerationRef.current;
    addController(controller);
    let sawStreamEvent = false;
    let streamedRunId: string | null = null;
    let followQueuedId: string | null = null;
    try {
      const queued = await client.streamChat({
        conversation_id: conversationId ?? undefined,
        message,
        attachments: attachments.length ? attachments : undefined,
        model_profile_id: profile || undefined,
        idempotency_key: crypto.randomUUID(),
        origin: "worker",
      }, (event) => {
        if (!controllerOwnsGeneration(controller, generation)) return;
        sawStreamEvent = true;
        if (event.type === "message_start") streamedRunId = event.run_id;
        acceptLiveEvent(event, generation);
      }, controller.signal);
      // Abort is a successful `undefined` return in the SDK. Check ownership
      // before interpreting that value as a naturally completed live turn.
      if (!controllerOwnsGeneration(controller, generation)) return false;
      if (queued) {
        const queuedConversationId = queued.conversation_id ?? conversationId;
        const queuedMessageId = queued.message_id ?? `queued-${crypto.randomUUID()}`;
        activeRunRef.current = queued.run_id;
        liveConversationRef.current = queuedConversationId;
        if (queuedConversationId) onWorkingChange?.(queuedConversationId, true);
        setLocalQueuedMessages((current) => current.some((item) => item.id === queuedMessageId)
          ? current
          : [...current, {
            id: queuedMessageId,
            role: "user",
            content: message,
            attachments,
            created_at: new Date().toISOString(),
          }]);
        // A 202 queue receipt carries no stream. When no other stream is
        // open (the active turn was started elsewhere or the local follow
        // already dropped), attach a follow after this send's controller is
        // released, or the live turn and the queued turn are both invisible.
        if (controllersRef.current.size === 1) {
          followQueuedId = queuedConversationId;
        }
      } else if (sawStreamEvent) {
        if (streamedRunId && activeRunRef.current !== streamedRunId) return false;
        const id = liveConversationRef.current ?? conversationId;
        if (id) {
          await loadConversation(id);
          if (
            !controllerOwnsGeneration(controller, generation)
            || (streamedRunId && activeRunRef.current !== streamedRunId)
          ) return false;
          setEvents([]);
        }
        activeRunRef.current = null;
        liveConversationRef.current = null;
      }
      onChanged();
      return false;
    } catch (reason) {
      if (controllerOwnsGeneration(controller, generation)) {
        setError(reasonText(reason));
        if (liveConversationRef.current) {
          setContinuity("Live updates paused. The run is still governed server-side.");
          setRetryFollow(true);
        }
      }
      return reason instanceof BoltrigApiError && reason.status === 413;
    } finally {
      const followStillOwned = Boolean(
        followQueuedId
        && conversationGenerationRef.current === generation
        && controllersRef.current.has(controller)
      );
      removeController(controller);
      if (followQueuedId && followStillOwned) void reattach(followQueuedId, 0, true);
    }
  }

  async function stop() {
    const generation = conversationGenerationRef.current;
    const ownerConversationId = conversationId;
    const runId = activeRunRef.current ?? live.runId;
    abortStreams();
    try {
      if (runId) await client.cancelRun(runId);
      if (!stopStillOwnsRun(generation, ownerConversationId, runId)) return;
      activeRunRef.current = null;
      liveConversationRef.current = null;
      setContinuity("");
      setRetryFollow(false);
      if (ownerConversationId) {
        await loadConversation(ownerConversationId);
        if (
          conversationGenerationRef.current !== generation
          || selectedConversationRef.current !== ownerConversationId
          || activeRunRef.current !== null
        ) return;
        setEvents([]);
      }
    } catch (reason) {
      if (
        conversationGenerationRef.current !== generation
        || selectedConversationRef.current !== ownerConversationId
      ) return;
      // The cancel or reload did not reach the kernel: the run may still be
      // active server-side, so keep the refs and offer the reconnect path
      // instead of leaving a frozen live turn with no affordance.
      setError(reasonText(reason));
      if (liveConversationRef.current) {
        setContinuity("Stop was not confirmed. The run may still be active server-side.");
        setRetryFollow(true);
      }
    }
  }

  async function hydrateConversation(id: string, ownsLiveStream: boolean) {
    setConversationLoad({ conversationId: id, phase: "loading", error: "" });
    setError("");
    try {
      const thread = await loadConversation(id);
      // A slower request for a prior selection has no authority to settle the
      // current route's loading state or attach a follow stream.
      if (selectedConversationRef.current !== id) return;
      setConversationLoad({ conversationId: id, phase: "ready", error: "" });
      if (
        thread.active_run_id
        && !ownsLiveStream
        && controllersRef.current.size === 0
      ) {
        activeRunRef.current = thread.active_run_id;
        void reattach(id, 0, true);
      }
    } catch (reason) {
      if (selectedConversationRef.current !== id) return;
      setConversationLoad({
        conversationId: id,
        phase: "error",
        error: reasonText(reason),
      });
    }
  }

  function retryConversationLoad() {
    if (!conversationId) return;
    const ownsLiveStream = Boolean(
      liveConversationRef.current === conversationId
      && controllersRef.current.size > 0
    );
    void hydrateConversation(conversationId, ownsLiveStream);
  }

  async function loadConversation(id: string) {
    const [thread, artifactResult, list] = await Promise.all([
      client.conversation(id),
      client.artifacts({ conversationId: id, limit: 25 }).catch(() => ({
        artifacts: [] as Artifact[],
        next_cursor: null,
      })),
      client.conversations(),
    ]);
    // A slow load must not clobber the view once the selection has moved on;
    // callers still receive the thread for their own bookkeeping.
    if (selectedConversationRef.current !== id) return thread;
    const summary = list.conversations.find((conversation) => conversation.id === id);
    if (!summary) {
      throw new Error("Conversation details are unavailable.");
    }
    onWorkingChange?.(id, Boolean(thread.active_run_id));
    const loadedMessageIds = new Set(thread.messages.map((message) => message.id));
    setLocalQueuedMessages((current) => current.filter((message) => !loadedMessageIds.has(message.id)));
    setMessages(thread.messages);
    setModelContext(thread.model_context ?? null);
    setArtifacts(artifactResult.artifacts);
    setArtifactCursor(artifactResult.next_cursor ?? null);
    setConversationTitle(summary.title || "Untitled task");
    setConversationStatus(summary.status);
    return thread;
  }

  async function loadMoreArtifacts() {
    if (!conversationId || !artifactCursor || loadingArtifacts) return;
    const requestedConversationId = conversationId;
    setLoadingArtifacts(true);
    try {
      const result = await client.artifacts({
        conversationId: requestedConversationId,
        limit: 25,
        cursor: artifactCursor,
      });
      if (selectedConversationRef.current !== requestedConversationId) return;
      setArtifacts((current) => {
        const known = new Set(current.map((artifact) => artifact.id));
        return [
          ...current,
          ...result.artifacts.filter((artifact) => !known.has(artifact.id)),
        ];
      });
      setArtifactCursor(result.next_cursor ?? null);
    } catch (reason) {
      if (selectedConversationRef.current === requestedConversationId) {
        setError(reasonText(reason));
      }
    } finally {
      if (selectedConversationRef.current === requestedConversationId) {
        setLoadingArtifacts(false);
      }
    }
  }

  async function refreshArtifacts(id: string) {
    const result = await client.artifacts({ conversationId: id, limit: 25 });
    if (selectedConversationRef.current !== id) return;
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
    const generation = conversationGenerationRef.current;
    let followedRunId = activeRunRef.current;
    let followNextRun = false;
    addController(controller);
    try {
      const result = await client.followConversation(id, (frame) => {
        if (!controllerOwnsGeneration(controller, generation)) return;
        if (frame.event.type === "message_start") followedRunId = frame.event.run_id;
        followCursorRef.current = frame.cursor;
        if (frame.replay_truncated) {
          setContinuity(
            "Earlier live activity aged out of the bounded replay window. "
            + "The durable transcript will refresh when the turn settles.",
          );
        }
        acceptLiveEvent(frame.event, generation);
      }, { since, signal: controller.signal });
      if (
        !controllerOwnsGeneration(controller, generation)
        || (followedRunId && activeRunRef.current !== followedRunId)
      ) return;
      followCursorRef.current = result.cursor;
      if (result.status !== "aborted") {
        const thread = await loadConversation(id);
        if (
          !controllerOwnsGeneration(controller, generation)
          || (followedRunId && activeRunRef.current !== followedRunId)
        ) return;
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
      if (controllerOwnsGeneration(controller, generation)) {
        setError(reasonText(reason));
        setContinuity("Live updates paused. Reconnect to continue following this run.");
        setRetryFollow(true);
      }
    } finally {
      const nextRunStillOwned = Boolean(
        followNextRun
        && controllerOwnsGeneration(controller, generation)
      );
      removeController(controller);
      if (nextRunStillOwned) void reattach(id, 0, true);
    }
  }

  function acceptLiveEvent(
    event: ChatEvent,
    generation = conversationGenerationRef.current,
  ) {
    if (conversationGenerationRef.current !== generation) return;
    if (event.type === "steer_queued") {
      const id = event.conversation_id ?? conversationId;
      if (id) void loadConversation(id).catch(() => undefined);
    } else if (event.type === "steer_consumed") {
      if (event.message_id) {
        setConsumedSteerIds((current) => current.includes(event.message_id!)
          ? current
          : [...current, event.message_id!]);
      }
    } else if (event.type === "artifact") {
      const id = liveConversationRef.current ?? conversationId;
      if (id) {
        void refreshArtifacts(id).catch(() => {
          if (conversationGenerationRef.current === generation) {
            setContinuity("An output is ready. Refresh the task if it is not listed yet.");
          }
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
    if (event.type === "message_end" || event.type === "cancelled") {
      // Settle the locally-observed duration for this run so the durable
      // transcript can keep stating what this client actually measured.
      const started = liveStartsRef.current.get(event.run_id);
      if (started != null) {
        const seconds = Math.max(0, Math.round((Date.now() - started) / 1_000));
        setTurnDurations((current) => ({ ...current, [event.run_id]: seconds }));
      }
    }
    if (event.type === "message_start") {
      if (!liveStartsRef.current.has(event.run_id)) {
        liveStartsRef.current.set(event.run_id, Date.now());
      }
      const priorRun = activeRunRef.current;
      activeRunRef.current = event.run_id;
      liveConversationRef.current = event.conversation_id;
      onWorkingChange?.(event.conversation_id, true);
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

  function controllerOwnsGeneration(
    controller: AbortController,
    generation: number,
  ) {
    return conversationGenerationRef.current === generation
      && controllersRef.current.has(controller)
      && !controller.signal.aborted;
  }

  function stopStillOwnsRun(
    generation: number,
    ownerConversationId: string | null,
    // Widened rather than coerced at the call site: the caller's id is
    // `activeRunRef.current ?? live.runId`, and live.runId is optional. Passing
    // `?? null` there would turn undefined into null and make the identity
    // check below false for a turn that has no run id yet — the opposite of
    // what it is asking.
    runId: string | null | undefined,
  ) {
    return conversationGenerationRef.current === generation
      && selectedConversationRef.current === ownerConversationId
      && (activeRunRef.current ?? live.runId) === runId;
  }

  function abortStreams() {
    for (const controller of controllersRef.current) controller.abort();
    controllersRef.current.clear();
    setLoading(false);
  }

  function closeTaskDetails() {
    setTaskDetailsOpen(false);
    window.setTimeout(() => taskDetailsTriggerRef.current?.focus(), 0);
  }

  async function controlsChanged() {
    if (conversationId) await loadConversation(conversationId);
    onChanged();
  }

  // One Familiar Stage per client (ADR 0025). The decided console uses it in
  // the New-chat voice invitation and, for the life of a call, centred above
  // the conversation. Main responses have no author identity in the current
  // protocol, so they do not borrow a child subagent's Stage or name.
  const stageIsHero = messages.length === 0 && events.length === 0;
  const stageMode: FamiliarPresentationMode = pageHidden
    ? "minimised"
    : callActive
      ? "voice"
      : "conversation";
  // The turn facts both bodies read. StageBody picks which one depicts them.
  const stageInput: StageTurnInput = {
    loading,
    hasLiveEvents: events.length > 0,
    liveEnded: live.ended,
    voiceSpeaking: voiceActivity.speaking,
    voiceLevel: voiceActivity.level,
    voiceBands: voiceActivity.bands ?? null,
    voiceOnset: voiceActivity.onset,
  };
  const stageState = familiarStateFromTurn(stageInput);
  const stage = (
    <StageBody input={stageInput} mode={stageMode} phenotype={phenotype} turn={live} />
  );

  // The decided target's New screen is chrome-free: no header row, the glyph
  // and question are the top of the surface. A conversation (or a live call)
  // brings the header back.
  const isNewState = stageIsHero && !conversationId;
  const showHeader = !isNewState || callActive;

  // The header count is conversation-wide: settled messages carry their
  // events, so subagents from earlier turns stay counted after their run
  // ends, deduplicated by child run.
  const conversationSubagentCount = useMemo(() => {
    const seen = new Set<string>();
    for (const message of visibleMessages) {
      if (!message.events?.length) continue;
      for (const agent of normalizeEvents(message.events).subagents) {
        seen.add(agent.childRunId || agent.key);
      }
    }
    for (const agent of live.subagents) seen.add(agent.childRunId || agent.key);
    return seen.size;
  }, [visibleMessages, live]);

  // Live voice is feature-guarded the same way VoiceCall guards itself: the
  // affordances render only where the call control is actually mounted.
  const voiceAvailable = (
    typeof client.createCall === "function"
    && (!conversationId || conversationStatus === "active")
  );
  const headerTitle = conversationStatus === "closed"
    ? "Closed conversation"
    : loadingConversation
      ? "Loading conversation…"
      : conversationLoadError
        ? "Conversation unavailable"
        : conversationId
          ? (conversationTitle || "Untitled task")
          : "New chat";

  // The round empty-draft primary starts the call through the mounted VoiceCall
  // control, so call creation, capability fallbacks and media teardown stay in
  // one place while the dock itself remains visually quiet.
  function startVoiceFromComposer() {
    const dock = voiceDockRef.current;
    const buttons = dock ? [...dock.querySelectorAll("button")] : [];
    const start = dock?.querySelector<HTMLButtonElement>(
      ".voice-idle > button.primary-button",
    ) ?? (buttons.length === 1 ? (buttons[0] as HTMLButtonElement) : null);
    if (start) {
      start.click();
    } else {
      setError("Live voice is not ready here. Use the call controls beside the composer.");
    }
  }

  function fillDraft(text: string) {
    setDraft(text);
    window.setTimeout(() => draftInputRef.current?.focus(), 0);
  }

  function promptForOutput() {
    const seed = "Create a file or site";
    setDraft((current) => current.trim() ? current : seed);
    if (compactTaskDetails) setTaskDetailsOpen(false);
    window.setTimeout(() => {
      if (phone) {
        document.querySelector<HTMLInputElement>(".m-composer .m-input")?.focus();
      } else {
        draftInputRef.current?.focus();
      }
    }, 0);
  }

  function dismissVoiceBanner() {
    setVoiceBanner(false);
    try {
      localStorage.setItem("boltrig-worker-voice-banner-dismissed", "true");
    } catch {
      // This is presentation-only state; the call control remains available.
    }
  }

  const composer = (
    <Composer
      busy={loading}
      disabled={Boolean(conversationId) && (!conversationReady || conversationStatus !== "active")}
      closed={conversationStatus === "closed"}
      conversationKey={conversationId}
      profiles={profiles}
      profile={profile}
      attachmentLimits={attachmentLimits}
      onProfile={setProfile}
      onSend={send}
      onStop={stop}
      value={draft}
      onChange={setDraft}
      inputRef={draftInputRef}
      tech={tech}
      newContext={isNewState}
      unavailable={Boolean(conversationLoadError)}
      voicePrimary={voiceAvailable && !callActive
        ? { onStart: startVoiceFromComposer }
        : undefined}
      voice={(!conversationId || conversationStatus === "active") ? (
        <span className="voice-dock" ref={voiceDockRef}>
          <VoiceCall
            conversationId={conversationId}
            conversationTitle={conversationTitle || undefined}
            modelProfileId={profile || undefined}
            onConversation={onConversation}
            onError={setError}
            onFamiliarActivity={setVoiceActivity}
            onCallActive={setCallActive}
            embedded
            showOptions={false}
          />
        </span>
      ) : undefined}
    />
  );

  // Tabs render live entries while their turn is still the live turn (status
  // words keep updating); after it settles, the snapshot taken at open keeps
  // each tab readable. The runId tag stops a later turn's colliding key from
  // substituting its own, unrelated entry.
  const tabAgents = openTabs.map((tab) =>
    (live.runId === tabsRunId
      ? live.subagents.find((entry) => entry.key === tab.key)
      : undefined) ?? tab.agent);

  // The task-details trigger renders once, at the same tree position for
  // every width, so a breakpoint flip never detaches the node mid-measure:
  // the mobile/console swap happens beneath it. Its placement is CSS.
  if (phone) {
    // The mobile surface replaces the console conversation, not the chat
    // contract: the task-details sheet (artifacts, run facts, conversation
    // controls) stays reachable through the same trigger/scrim/inert cycle
    // the compact console uses.
    return (
      <>
      {compactTaskDetails && conversationReady && (
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
        <MobileChat
          key={`mobile:${conversationId ?? "new"}`}
          busy={loading || (Boolean(live.runId) && !live.ended)}
          closed={conversationStatus === "closed"}
          composerDisabled={Boolean(conversationId) && (
            !conversationReady || conversationStatus !== "active"
          )}
          composerValue={draft}
          continuity={continuity}
          conversationLoadError={conversationLoadError}
          error={error}
          loadingConversation={loadingConversation}
          messages={transcriptMessages}
          newState={isNewState}
          onBack={() => navigate("home")}
          onComposerChange={setDraft}
          onReconnect={() => {
            if (!conversationId) return;
            void reattach(
              conversationId,
              followCursorRef.current,
              followCursorRef.current === 0,
            );
          }}
          onRetryConversation={retryConversationLoad}
          onRespondHitl={async (id, decision) => {
            try {
              const result = await client.respondHitl(id, decision, "");
              return result.status === "ok" || result.status === "answered";
            } catch {
              return false;
            }
          }}
          onSend={() => {
            const text = draft.trim();
            if (!text) return;
            const owner = conversationId;
            setDraft("");
            void send(text, []).then((restore) => {
              if (restore && selectedConversationRef.current === owner) {
                setDraft((current) => current || text);
              }
            });
          }}
          onSteerQueued={(message) => {
            setDraft(message.content ?? "");
            setContinuity("Queued instruction loaded into the composer.");
            window.setTimeout(() => {
              document.querySelector<HTMLInputElement>(".m-composer .m-input")?.focus();
            }, 0);
          }}
          onStop={() => void stop()}
          queuedMessages={queuedMessages}
          retryFollow={retryFollow}
          subtitle={conversationSubagentCount > 0
            ? `${conversationSubagentCount} ${conversationSubagentCount === 1 ? "subagent" : "subagents"}`
            : conversationStatus === "closed" ? "Closed" : ""}
          title={headerTitle}
          turn={railTurn}
          turnIsAnswerable={railTurnIsLive}
          turnIsLive={Boolean(live.runId && live.runId === railTurn.runId)}
        />
        {taskDetailsOpen && (
          <button
            aria-label="Dismiss task details"
            className="task-details-scrim"
            onClick={closeTaskDetails}
            type="button"
          />
        )}
        {conversationReady && <RightRail
          key={`rail:${conversationId ?? "new"}`}
          artifacts={artifacts}
          integrationSources={integrationSources}
          sources={sources}
          turn={railTurn}
          artifactCursor={artifactCursor}
          loadingArtifacts={loadingArtifacts}
          onLoadMoreArtifacts={loadMoreArtifacts}
          onCreateOutput={conversationStatus === "closed" ? undefined : promptForOutput}
          compact
          mobileActions={conversationId && conversationStatus ? (
            <ConversationControls
              conversationId={conversationId}
              lastAssistantMessageId={lastAssistantMessageId}
              onChanged={() => void controlsChanged().catch((reason) => setError(reasonText(reason)))}
              onDeleted={() => {
                closeTaskDetails();
                void controlsChanged().catch((reason) => setError(reasonText(reason)));
              }}
              status={conversationStatus}
              title={conversationTitle || "Untitled task"}
            />
          ) : undefined}
          open={taskDetailsOpen}
          panelRef={taskDetailsPanelRef}
          onClose={closeTaskDetails}
        />}
      </>
    );
  }

  return (
    <>
      {compactTaskDetails && !isNewState && conversationReady && (
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
    {sectionRunId && (
      // The run-section drawing covers the conversation surface; the layout
      // beneath stays MOUNTED (display:none) so the composer draft, staged
      // attachments and any live voice call survive the visit. The run id is
      // pinned at open, so a settling turn neither closes the drawing under
      // the reader nor re-arms it for the next run.
      <RunSectionView
        runId={sectionRunId}
        title={conversationTitle || undefined}
        devDetails={tech}
        familiarsByRunId={Object.fromEntries(
          [...live.subagents, ...openTabs.map((tab) => tab.agent)]
            .filter((agent) => agent.childRunId)
            .map((agent) => [agent.childRunId, agent.familiarGenotype]),
        )}
        onBack={() => {
          setSectionRunId(null);
          draftInputRef.current?.focus();
        }}
      />
    )}
    <div
      className="chat-layout"
      data-rail-collapsed={isNewState || (!compactTaskDetails && !railOpen) ? "true" : undefined}
      style={sectionRunId ? { display: "none" } : undefined}
    >
      <main className="chat-main">
        {showHeader ? (
        <header className="chat-header">
          <div className="agent-heading">
            <div className="chat-header-familiar">
              <button
                aria-label={voiceAvailable
                  ? `Talk to the chief of staff about ${headerTitle}`
                  : `${headerTitle}. Voice is unavailable for this conversation`}
                className="chat-header-familiar-action"
                disabled={!voiceAvailable || callActive}
                onClick={startVoiceFromComposer}
                title={voiceAvailable
                  ? "Talk to the chief of staff instead"
                  : "Voice is available only for active conversations"}
                type="button"
              />
              <span aria-hidden className="chat-header-familiar-mark">
                <FamiliarBadge
                  label="chief of staff"
                  state={stageState.working ? "working" : "ready"}
                />
              </span>
              <h1>{headerTitle}</h1>
            </div>
            {/* The decided target sets a muted count beside the title. It is
                stated only when there is something to count, so an empty chat
                does not carry a "0 subagents" label the design never draws.
                The count is conversation-wide: settled turns stay counted. */}
            {conversationSubagentCount > 0 && (
              <span className="chat-header-sub">
                {conversationSubagentCount} {conversationSubagentCount === 1 ? "subagent" : "subagents"}
              </span>
            )}
          </div>
          <div className="chat-header-actions">
            <ThemeToggle />
            {/* Desktop-only rail toggle. Below the compact breakpoint the
                task-details trigger remains the single rail affordance
                (39c14bd: exactly one trigger at every width). */}
            {!compactTaskDetails && (
              <button
                aria-controls="worker-task-details"
                aria-expanded={railOpen}
                aria-label={railOpen ? "Hide the task panel" : "Show the task panel"}
                className="icon-button rail-toggle"
                onClick={() => setRailOpen((open) => !open)}
                title="Toggle panel"
                type="button"
              >
                <svg aria-hidden fill="none" height="15" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 24 24" width="15">
                  <rect height="14" rx="2.5" width="18" x="3" y="5" />
                  <line x1="15" x2="15" y1="5" y2="19" />
                </svg>
              </button>
            )}
          </div>
        </header>
        ) : null}
        {callActive && (
          <div className="voice-stage" aria-hidden={false}>{stage}</div>
        )}
        <div
          aria-label="Conversation transcript"
          className={isNewState ? "transcript new-chat-transcript" : "transcript"}
          onScroll={(event) => {
            const transcript = event.currentTarget;
            followTranscriptRef.current = (
              transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight < 80
            );
          }}
          ref={transcriptRef}
          role="region"
          tabIndex={0}
        >
          {isNewState ? (
            <Welcome onStarter={fillDraft}>{isNewState ? composer : null}</Welcome>
          ) : null}
          {conversationId && loadingConversation && (
            <p className="notice" role="status">Loading conversation…</p>
          )}
          {conversationId && conversationLoadError && (
            <p className="notice" role="alert">
              Could not load this conversation. {conversationLoadError}{" "}
              <button
                className="secondary-button"
                onClick={retryConversationLoad}
                type="button"
              >
                Retry conversation
              </button>
            </p>
          )}
          {transcriptMessages.map((message) => (
            <Message
              key={message.id}
              message={message}
              tech={tech}
              durationSeconds={message.run_id ? turnDurations[message.run_id] : undefined}
              // Settled turns' chips stay static marks: their entries' keys
              // belong to a dead index space and cannot honestly open a tab.
            />
          ))}
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
          {events.length > 0 && (
            <LiveTurn
              events={events}
              turn={live}
              tech={tech}
              startedAt={live.runId ? liveStartsRef.current.get(live.runId) ?? null : null}
              onOpenSubagent={canOpenPanes && railTurnIsLive ? openSubagentTab : undefined}
            />
          )}
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
        {queuedMessages.length > 0 && (
          <QueuedMessages
            messages={queuedMessages}
            onSteer={(message) => {
              setDraft(message.content ?? "");
              setContinuity("Queued instruction loaded into the composer.");
              window.setTimeout(() => draftInputRef.current?.focus(), 0);
            }}
          />
        )}
        {!isNewState && composer}
        {isNewState && !callActive && voiceAvailable && voiceBanner && (
          <div className="voice-intro">
            <StageBody
              input={stageInput}
              label="chief of staff"
              mode="conversation"
              phenotype={phenotype}
              turn={live}
            />
            <span className="voice-intro-copy">
              <strong>Talk to boltrig</strong>
              <small>Say it out loud and it starts while you speak</small>
            </span>
            <button className="voice-intro-start" onClick={startVoiceFromComposer} type="button">Start</button>
            <button
              aria-label="Not now"
              className="voice-intro-dismiss"
              onClick={dismissVoiceBanner}
              title="Not now"
              type="button"
            >
              <svg aria-hidden fill="none" height="12" stroke="currentColor" strokeLinecap="round" strokeWidth="2.3" viewBox="0 0 24 24" width="12">
                <line x1="6" x2="18" y1="6" y2="18" />
                <line x1="18" x2="6" y1="6" y2="18" />
              </svg>
            </button>
          </div>
        )}
      </main>
      {openTabs.length > 0 && canOpenPanes && (
        <SubagentTabs
          subagents={tabAgents}
          openKeys={openTabs.map((tab) => tab.key)}
          activeKey={activeSubagentKey}
          parentRunId={tabsRunId ?? undefined}
          turnEnded={live.runId === tabsRunId ? live.ended : true}
          onSelect={setActiveSubagentKey}
          onClose={closeSubagentTab}
          onCloseAll={closeAllSubagentTabs}
        />
      )}
      {compactTaskDetails && taskDetailsOpen && (
        <button
          aria-label="Dismiss task details"
          className="task-details-scrim"
          onClick={closeTaskDetails}
          type="button"
        />
      )}
      {!isNewState && conversationReady && <RightRail
        key={`rail:${conversationId ?? "new"}`}
        artifacts={artifacts}
        integrationSources={integrationSources}
        sources={sources}
        turn={railTurn}
        artifactCursor={artifactCursor}
        loadingArtifacts={loadingArtifacts}
        onLoadMoreArtifacts={loadMoreArtifacts}
        onCreateOutput={conversationStatus === "closed" ? undefined : promptForOutput}
        onSeeWhatRan={canOpenPanes && railTurn.runId
          ? () => setSectionRunId(railTurn.runId ?? null)
          : undefined}
        compact={compactTaskDetails}
        open={compactTaskDetails ? taskDetailsOpen : railOpen}
        panelRef={taskDetailsPanelRef}
        onClose={closeTaskDetails}
      />}
    </div>
    </>
  );
}

function ThemeToggle() {
  const [theme, setTheme] = useState(appliedTheme);
  return (
    <button
      aria-label="Toggle theme"
      className="icon-button theme-toggle"
      onClick={() => setTheme(toggleTheme())}
      title={theme === "dark" ? "Switch to light" : "Switch to dark"}
      type="button"
    >
      {theme === "dark" ? (
        <svg aria-hidden fill="none" height="15" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" viewBox="0 0 24 24" width="15">
          <path d="M12 7.6a4.4 4.4 0 1 1 0 8.8 4.4 4.4 0 0 1 0-8.8z" />
          <path d="M12 2v2.2M12 19.8V22M4.3 4.3l1.6 1.6M18.1 18.1l1.6 1.6M2 12h2.2M19.8 12H22M4.3 19.7l1.6-1.6M18.1 5.9l1.6-1.6" />
        </svg>
      ) : (
        <svg aria-hidden fill="none" height="15" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" viewBox="0 0 24 24" width="15">
          <path d="M20 14.5A8.2 8.2 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z" />
        </svg>
      )}
    </button>
  );
}

// Starter icon paths, traced from the design's icon set (stroke, 24 viewBox).
const STARTERS: Array<{ title: string; desc: string; icon: string[] }> = [
  {
    title: "Find something out",
    desc: "Read across your systems and come back with an answer",
    icon: [
      "M4.5 4.5h6a3 3 0 0 1 3 3v12a2.5 2.5 0 0 0-2.5-2.5h-6.5z",
      "M19.5 4.5h-6a3 3 0 0 0-3 3v12a2.5 2.5 0 0 1 2.5-2.5h6.5z",
    ],
  },
  {
    title: "Draft something",
    desc: "Written in your voice, and sent to nobody until you say",
    icon: ["M6 3.5h7l5 5v12H6z", "M13 3.5V9h5"],
  },
  {
    title: "Work through a list",
    desc: "The same job across many records, a helper on each",
    icon: ["M4 4.5h16v5H4zM4 14.5h16v5H4z", "M7.5 7h.01M7.5 17h.01"],
  },
  {
    title: "Keep an eye on something",
    desc: "A standing goal it keeps pursuing until you stop it",
    icon: ["M5 12.5l4.5 4.5L19 7"],
  },
];

// The decided target opens a new chat with a quiet mark, one question and four
// starters. It does NOT open with the Stage at hero size: that placement came
// from ADR 0025 and the new target supersedes it here, which also removes the
// unbounded square that pushed the composer off a short window. Clicking a
// starter fills the composer draft; it never sends.
function Welcome({
  onStarter,
  children,
}: {
  onStarter?(text: string): void;
  children: React.ReactNode;
}) {
  return (
    <section className="welcome">
      <h1>What needs doing?</h1>
      {children}
      <div className="starters">
        {STARTERS.map(({ title, desc, icon }) => (
          <button
            className="starter-card"
            key={title}
            onClick={() => onStarter?.(title)}
            title={desc}
            type="button"
          >
            <span aria-hidden className="starter-icon">
              <svg fill="none" height="16" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" viewBox="0 0 24 24" width="16">
                {icon.map((d) => <path d={d} key={d} />)}
              </svg>
            </span>
            <span className="starter-title">{title}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

function Message({
  message,
  tech,
  durationSeconds,
  onOpenSubagent,
}: {
  message: ChatMessage;
  tech: boolean;
  durationSeconds?: number;
  onOpenSubagent?(agent: SubagentEntry): void;
}) {
  const turn = useMemo(() => normalizeEvents(message.events ?? []), [message.events]);
  return (
    <article className={`message ${message.role}`}>
      <div className="message-content">
        {turn.degraded && (
          <p className="notice" role="status">
            This response used a degraded fallback; treat its result as incomplete.
          </p>
        )}
        <OrderedWorkTranscript
          content={message.content}
          events={message.events ?? []}
          turn={turn}
          settled
          durationSeconds={durationSeconds ?? null}
        />
        {message.attachments?.map((item) => (
          <button
            type="button"
            className="attachment"
            key={attachmentIdentity(item)}
            onClick={() => downloadAttachment(item)}
          >
            ▧ {item.name}{item.size != null ? ` · ${formatBytes(item.size)}` : ""}
          </button>
        ))}
        {message.events?.length ? (
          <TurnDecisions turn={turn} settled tech={tech} onOpenSubagent={onOpenSubagent} />
        ) : null}
      </div>
    </article>
  );
}

function LiveTurn({
  events,
  turn,
  tech,
  startedAt,
  onOpenSubagent,
}: {
  events: ChatEvent[];
  turn: NormalizedTurn;
  tech: boolean;
  startedAt: number | null;
  onOpenSubagent?(agent: SubagentEntry): void;
}) {
  return (
    <article className="message assistant live">
      <div className="message-content">
        <span aria-atomic="true" className="chat-live-announcement" role="status">
          {turn.ended
            ? "Response complete."
            : turn.text
              ? "Response in progress."
              : "Boltrig is working."}
        </span>
        {turn.degraded && (
          <p className="notice" role="status">
            This response used a degraded fallback; treat its result as incomplete.
          </p>
        )}
        {turn.reasoning && <details><summary>Working notes</summary><p>{turn.reasoning}</p></details>}
        <OrderedWorkTranscript
          content={turn.text}
          emptyText="Working…"
          events={events}
          turn={turn}
          startedAt={startedAt}
        />
        <TurnDecisions turn={turn} tech={tech} onOpenSubagent={onOpenSubagent} />
        {/* The raw profile id is developer detail (the plain console already
            names the model in the composer chip). */}
        {tech && turn.modelRouting && (
          <p className="routing-note">
            {turn.modelRouting.selectedProfileId} · {turn.modelRouting.routingClass}
            {turn.modelRouting.overridden ? " · policy adjusted" : ""}
          </p>
        )}
      </div>
    </article>
  );
}

/** Everything below the prose and its compact tool receipt: the subagent chip
 * row, then decision cards (approvals and questions) in stream order. */
function TurnDecisions({
  turn,
  settled = false,
  tech,
  onOpenSubagent,
}: {
  turn: NormalizedTurn;
  settled?: boolean;
  tech: boolean;
  onOpenSubagent?(agent: SubagentEntry): void;
}) {
  const decisions = turn.timeline.filter(
    (item) => item.kind === "hitl" || item.kind === "question",
  );
  if (turn.subagents.length === 0 && decisions.length === 0) return null;
  return (
    <>
      <SubagentChips
        subagents={turn.subagents}
        turnEnded={turn.ended || settled}
        tech={tech}
        onOpenSubagent={onOpenSubagent}
      />
      {decisions.map((item) => {
        if (item.kind === "hitl") {
          // A settled transcript replays the hitl event, but its request
          // belongs to a dead turn; the card must never invite re-answering.
          if (settled) return <SettledApproval entry={item.entry} tech={tech} key={item.key} />;
          return (
            <InlineApproval
              entry={item.entry}
              tech={tech}
              disabled={turn.ended}
              key={item.key}
            />
          );
        }
        if (item.kind === "question") {
          // A settled transcript replays the question event, but its HITL
          // request is already resolved; rendering the interactive card would
          // invite re-answering (including re-typing secure secrets) against
          // a dead request.
          if (settled) return (
            <div className="approval-card live-question" key={item.key}>
              <strong>Question from this run</strong>
              <p>{item.entry.prompt}</p>
              <p className="muted small">
                This question was part of a completed turn and is no longer
                answerable.
              </p>
            </div>
          );
          return <LiveQuestionCard question={item.entry} key={item.key} />;
        }
        return null;
      })}
    </>
  );
}

function QueuedMessages({
  messages,
  onSteer,
}: {
  messages: ChatMessage[];
  onSteer(message: ChatMessage): void;
}) {
  return (
    <section aria-label="Queued messages" className="queued-messages">
      {messages.map((message) => (
        <article className="queued-message" data-message-id={message.id} key={message.id}>
          <span aria-hidden className="queued-message-glyph">↳</span>
          <div className="queued-message-copy">
            <p>{message.content || "Queued instruction"}</p>
            {message.attachments && message.attachments.length > 0 && (
              <small>{message.attachments.length} attachment{message.attachments.length === 1 ? "" : "s"}</small>
            )}
          </div>
          <button
            aria-label={`Steer queued message: ${message.content || "Queued instruction"}`}
            className="queued-message-steer"
            onClick={() => onSteer(message)}
            title="Load this queued instruction into the composer"
            type="button"
          >
            ↳ Steer
          </button>
        </article>
      ))}
    </section>
  );
}

interface ComposerProps {
  busy: boolean;
  disabled: boolean;
  closed: boolean;
  /** Resets staged, conversation-owned inputs without remounting VoiceCall. */
  conversationKey: string | null;
  profiles: ModelProfile[];
  profile: string;
  attachmentLimits: ChatAttachmentLimits;
  /** The draft lives with the caller so starter cards can fill it. */
  value: string;
  onChange: React.Dispatch<React.SetStateAction<string>>;
  inputRef?: RefObject<HTMLTextAreaElement>;
  /** Developer detail: raw profile ids on the model chip. */
  tech: boolean;
  /** When set (the New state only, with live voice verified reachable), an
      empty draft turns the primary button into "Start a voice call". */
  voicePrimary?: { onStart(): void };
  onProfile(value: string): void;
  onSend(message: string, files: ChatAttachment[]): Promise<boolean>;
  onStop(): Promise<void>;
  /** The voice control, so it sits with the other composer tools rather than
      crowding the title row. */
  voice?: React.ReactNode;
  /** The fresh-chat target centres the composer and hangs a truthful context
      rail below it. This changes presentation only; no policy is inferred. */
  newContext?: boolean;
  /** A failed state load is distinct from an in-progress load. */
  unavailable?: boolean;
}

function Composer({
  busy,
  disabled,
  closed,
  conversationKey,
  profiles,
  profile,
  attachmentLimits,
  value,
  onChange,
  inputRef,
  tech,
  voicePrimary,
  onProfile,
  onSend,
  onStop,
  voice,
  newContext = false,
  unavailable = false,
}: ComposerProps) {
  const [files, setFiles] = useState<ChatAttachment[]>([]);
  const [fileError, setFileError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const conversationKeyRef = useRef(conversationKey);
  conversationKeyRef.current = conversationKey;

  useLayoutEffect(() => {
    setFiles([]);
    setFileError("");
    if (input.current) input.current.value = "";
  }, [conversationKey]);

  async function addFiles(list: FileList | null) {
    if (!list) return;
    const owner = conversationKey;
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
    if (conversationKeyRef.current !== owner) return;
    setFiles((current) => [...current, ...added]);
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const message = value.trim();
    if (!message) return;
    onChange("");
    const sentFiles = files;
    const owner = conversationKey;
    setFiles([]);
    const restore = await onSend(message, sentFiles);
    if (conversationKeyRef.current !== owner) return;
    if (restore) {
      onChange((current) => current || message);
      setFiles((current) => current.length ? current : sentFiles);
    }
  }

  return (
    <form className={`composer${closed ? " closed" : ""}${newContext ? " new-context" : " conversation-context"}`} onSubmit={submit}>
      <div className="composer-frame">
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
            : unavailable
              ? "Conversation unavailable — retry above"
            : disabled
              ? "Loading conversation state…"
              : "Describe the work"
        }
        disabled={disabled}
        ref={inputRef}
        value={value}
        onChange={(event) => onChange(event.target.value)}
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
          <button type="button" className="icon-button" disabled={disabled} onClick={() => input.current?.click()} aria-label="Attach files">
            <svg aria-hidden fill="none" height="17" stroke="currentColor" strokeLinecap="round" strokeWidth="1.9" viewBox="0 0 24 24" width="17">
              <line x1="12" x2="12" y1="5" y2="19" />
              <line x1="5" x2="19" y1="12" y2="12" />
            </svg>
          </button>
          <button
            className="composer-posture"
            onClick={() => navigate("settings", "autonomy")}
            title="Open the per-action approval policy"
            type="button"
          >
            <span aria-hidden />
            Policy
          </button>
        </div>
        <div>
          {profiles.length > 0 && (
            <ModelChip
              profiles={profiles}
              value={profile}
              disabled={disabled}
              tech={tech}
              onChange={onProfile}
            />
          )}

          {busy && (
            <button className="stop-button" type="button" onClick={() => void onStop()}>
              ■ Stop
            </button>
          )}
          {newContext && (
            <button
              aria-label="Dictation unavailable"
              aria-disabled="true"
              className="icon-button composer-dictate"
              title="Dictation is not available in this client"
              type="button"
            >
              <svg aria-hidden fill="none" height="16" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" viewBox="0 0 24 24" width="16">
                <rect height="11" rx="3" width="6" x="9" y="3" />
                <path d="M5 11a7 7 0 0 0 14 0" />
                <line x1="12" x2="12" y1="18" y2="21" />
              </svg>
            </button>
          )}
          {voice}
          {/* The primary is dual: with a draft it sends (or queues); with an
              empty draft on the New state it starts a voice call. Only an
              explicit click starts a call - Enter on an empty draft stays
              inert, so a stray keystroke never opens a microphone. */}
          {voicePrimary && !value.trim() && !busy && !disabled ? (
            <button
              aria-label="Start a voice call"
              className="send-button voice-primary"
              onClick={() => voicePrimary.onStart()}
              title="Start a voice call"
              type="button"
            >
              <svg aria-hidden fill="currentColor" height="15" viewBox="0 0 24 24" width="15">
                <rect height="4" rx="1.2" width="2.4" x="4" y="10" />
                <rect height="10" rx="1.2" width="2.4" x="8.4" y="7" />
                <rect height="15" rx="1.2" width="2.4" x="12.8" y="4.5" />
                <rect height="6" rx="1.2" width="2.4" x="17.2" y="9" />
              </svg>
            </button>
          ) : (
            <button
              aria-label={busy ? "Queue next ↑" : "Send ↑"}
              className="send-button"
              disabled={disabled || !value.trim()}
              title={busy ? "Queue next" : "Send"}
              type="submit"
            >
              <svg aria-hidden fill="none" height="14" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.3" viewBox="0 0 24 24" width="14">
                <line x1="12" x2="12" y1="19" y2="5" />
                <polyline points="5 12 12 5 19 12" />
              </svg>
            </button>
          )}
        </div>
      </div>
      </div>
      {newContext && (
        <div className="composer-context" aria-label="Task context">
          <span className="composer-context-item" title="Project selection is not available in this client">
            <svg aria-hidden fill="none" height="14" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" viewBox="0 0 24 24" width="14">
              <path d="M4.5 4.5h6a3 3 0 0 1 3 3v12a2.5 2.5 0 0 0-2.5-2.5h-6.5z" />
              <path d="M19.5 4.5h-6a3 3 0 0 0-3 3v12a2.5 2.5 0 0 1 2.5-2.5h6.5z" />
            </svg>
            <span>No project selected</span>
          </span>
          <button className="composer-context-item" onClick={() => navigate("integrations")} type="button">
            <span aria-hidden className="composer-plugin-stack"><i>P</i><i>＋</i></span>
            <span>Plugins</span>
          </button>
          <span className="composer-context-hint">Everything it does is recorded</span>
        </div>
      )}
    </form>
  );
}

// A compact rail section: a quiet heading, at most one real action, and rows
// backed by the current conversation/run contracts. The floating surface owns
// the glass; sections deliberately own no card chrome or divider strokes.
function RailGroup({
  title,
  action,
  actionLabel,
  onAction,
  children,
}: {
  title: string;
  action?: string;
  actionLabel?: string;
  onAction?(): void;
  children: React.ReactNode;
}) {
  return (
    <section aria-label={title} className="rail-group">
      <div className="rail-group-head">
        <span>{title}</span>
        {action !== undefined && (
          onAction
            ? <button aria-label={actionLabel} className="rail-action" onClick={onAction} type="button">{action}</button>
            : <span className="rail-action" aria-hidden={false}>{action}</span>
        )}
      </div>
      {children}
    </section>
  );
}

function RailRow({
  tone,
  mark,
  label,
  meta,
  quiet,
  plain,
  onClick,
}: {
  tone?: "green" | "amber" | "red" | "unknown";
  mark?: React.ReactNode;
  label: string;
  meta?: string;
  quiet?: boolean;
  /** Rows such as the Outputs empty-state already have a section action and
      need no invented status dot or duplicate plus glyph. */
  plain?: boolean;
  onClick?(): void;
}) {
  const inner = (
    <>
      {mark
        ? <span className="rail-mark">{mark}</span>
        : plain
          ? null
          : <span className="rail-dot" style={{ background: `var(--${tone ?? "unknown"})` }} />}
      <span className="rail-label" data-quiet={quiet ? "true" : undefined}>{label}</span>
      {meta ? <span className="rail-meta">{meta}</span> : null}
    </>
  );
  if (!onClick) return <div className="rail-row">{inner}</div>;
  return (
    <button className="rail-row" data-interactive="true" onClick={onClick} type="button">
      {inner}
    </button>
  );
}

function SourceMark({ mediaType }: { mediaType: string }) {
  const kind = mediaType.startsWith("image/")
    ? "image"
    : mediaType.includes("zip") || mediaType.includes("archive")
      ? "archive"
      : mediaType.startsWith("text/")
        ? "text"
        : "file";
  const glyph = kind === "image" ? "▦" : kind === "archive" ? "▱" : kind === "text" ? "≡" : "↗";
  return <span aria-hidden className="rail-source-mark" data-kind={kind}>{glyph}</span>;
}

function IntegrationSourceMark({ id }: { id: string }) {
  if (id === "figma") {
    return (
      <span aria-hidden className="rail-integration-mark" data-integration="figma">
        <svg fill="none" viewBox="0 0 24 24">
          <path d="M8.5 2H12v7H8.5a3.5 3.5 0 1 1 0-7Z" fill="#f24e1e" />
          <path d="M12 2h3.5a3.5 3.5 0 0 1 0 7H12Z" fill="#ff7262" />
          <path d="M8.5 9H12v7H8.5a3.5 3.5 0 1 1 0-7Z" fill="#a259ff" />
          <circle cx="15.5" cy="12.5" fill="#1abcfe" r="3.5" />
          <path d="M8.5 16H12v3.5A3.5 3.5 0 1 1 8.5 16Z" fill="#0acf83" />
        </svg>
      </span>
    );
  }
  return (
    <span aria-hidden className="rail-integration-mark" data-integration={id}>
      {id.slice(0, 1).toUpperCase()}
    </span>
  );
}

function ToolSurfaceMark({ kind, tone }: {
  kind: RailToolSurface;
  tone: ReturnType<typeof railToolTone>;
}) {
  return (
    <span aria-hidden className="rail-tool-mark" data-kind={kind} data-tone={tone}>
      <svg fill="none" viewBox="0 0 24 24">
        {kind === "background" ? (
          <>
            <rect height="16" rx="2.5" width="18" x="3" y="4" />
            <path d="m7.5 9 2.5 2.5L7.5 14M13 14h3.5" />
          </>
        ) : (
          <>
            <rect height="11" rx="1.5" width="14" x="2.5" y="5" />
            <rect height="11" rx="1.5" width="14" x="7.5" y="8" />
          </>
        )}
      </svg>
    </span>
  );
}

function ViewSourcesMark() {
  return (
    <span aria-hidden className="rail-view-sources-mark">
      <svg fill="none" viewBox="0 0 24 24">
        <path d="m9.5 14.5 5-5M7.2 17.8l-1.1 1.1a3.5 3.5 0 0 1-5-5l3.2-3.2a3.5 3.5 0 0 1 5 0M16.8 6.2l1.1-1.1a3.5 3.5 0 0 1 5 5l-3.2 3.2a3.5 3.5 0 0 1-5 0" />
      </svg>
    </span>
  );
}

type RailToolSurface = "background" | "computer";

// ChatEvent has no generic process/session projection. Only an explicit tool
// identifier earns one of these screenshot sections; an ordinary tool call is
// already visible in the transcript's Work disclosure and is not relabelled.
function railToolSurface(verb: string): RailToolSurface | null {
  const normalized = verb.trim().toLowerCase().replaceAll("-", "_");
  if (
    normalized === "computer_use"
    || normalized.startsWith("computer.")
    || normalized.startsWith("computer_use.")
  ) return "computer";
  if (
    normalized === "background_process"
    || normalized.startsWith("background.")
    || normalized.startsWith("background_process.")
    || normalized.startsWith("process.background.")
  ) return "background";
  return null;
}

function railToolTone(status: string): "green" | "amber" | "red" | "unknown" {
  const normalized = status.toLowerCase();
  if (normalized === "pending" || normalized === "running" || normalized === "ok") {
    return "green";
  }
  if (
    normalized === "degraded"
    || normalized === "paused"
    || normalized === "pending_human"
  ) return "amber";
  // A completed tool result may carry a kernel reason string (grant_missing,
  // rate_limited, schema_invalid, …) rather than the literal word "error".
  // Any terminal status outside the bounded success/waiting set is therefore
  // a failure, matching the transcript's exact-details disclosure.
  return "red";
}

function railToolStatus(status: string): string {
  const normalized = status.toLowerCase();
  if (normalized === "pending") return "running";
  if (normalized === "pending_human") return "waiting for approval";
  if (normalized === "ok") return "done";
  if (normalized === "running" || normalized === "degraded" || normalized === "paused") {
    return normalized;
  }
  return "did not complete";
}

function subagentRailState(
  item: SubagentEntry,
  turnEnded: boolean,
): "done" | "working" | "degraded" | "failed" | "unknown" {
  if (item.status === "ok") return "done";
  if (item.status === "error") return "failed";
  if (item.status === "degraded") return "degraded";
  if (item.status === "running" || !turnEnded) return "working";
  return "unknown";
}

function subagentRailSummary(items: SubagentEntry[], turnEnded: boolean): string {
  const states = items.map((item) => subagentRailState(item, turnEnded));
  return (["done", "working", "degraded", "failed", "unknown"] as const)
    .flatMap((state) => {
      const count = states.filter((candidate) => candidate === state).length;
      if (count === 0) return [];
      if (state === "unknown") return [`${count} status unknown`];
      return [`${count} ${state}`];
    })
    .join(" · ");
}

interface RightRailProps {
  artifacts: Artifact[];
  integrationSources: IntegrationCatalogueEntry[];
  sources: ChatAttachment[];
  artifactCursor: string | null;
  loadingArtifacts: boolean;
  compact: boolean;
  open: boolean;
  panelRef: RefObject<HTMLElement>;
  turn: NormalizedTurn;
  /** Phone-only, real conversation mutations. Kept behind a disclosure so
      desktop/tablet floating rail chrome remains utility-only. */
  mobileActions?: React.ReactNode;
  onLoadMoreArtifacts(): Promise<void>;
  onCreateOutput?(): void;
  /** Opens the run-section drawing; offered only while the turn has a run. */
  onSeeWhatRan?(): void;
  onClose(): void;
}

function RightRail({
  artifacts,
  integrationSources,
  sources,
  artifactCursor,
  loadingArtifacts,
  compact,
  open,
  panelRef,
  turn,
  mobileActions,
  onLoadMoreArtifacts,
  onCreateOutput,
  onClose,
  onSeeWhatRan,
}: RightRailProps) {
  const [downloadError, setDownloadError] = useState("");
  const [materialized, setMaterialized] = useState<Record<string, string>>({});
  const backgroundTools = turn.tools.filter((tool) => railToolSurface(tool.verb) === "background");
  const computerTools = turn.tools.filter((tool) => railToolSurface(tool.verb) === "computer");

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
      <div className="rail-card chat-rail-glass">
      <RailGroup
        title="Outputs"
        action={onCreateOutput ? "+" : undefined}
        actionLabel={onCreateOutput ? "Create output" : undefined}
        onAction={onCreateOutput}
      >
        <div className="rail-body">
          {artifacts.length === 0 && (
            <RailRow
              label={onCreateOutput ? "Create a file or site" : "No outputs"}
              plain
              quiet
              onClick={onCreateOutput}
            />
          )}
          {artifacts.map((item) => {
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
        </div>
      </RailGroup>
      {turn.subagents.length > 0 && (
        <RailGroup title="Subagents">
          <RailRow
            quiet
            mark={(
              <span
                aria-label={turn.subagents.map((item) => item.name ?? item.task).join(", ")}
                className="rail-agent-stack"
                role="img"
              >
                {turn.subagents.slice(0, 3).map((item) => (
                  <FamiliarBadge
                    decorative
                    genotype={item.familiarGenotype}
                    key={item.key}
                    state={subagentRailState(item, turn.ended) === "working" ? "working" : "ready"}
                    label={item.name ?? item.task}
                  />
                ))}
              </span>
            )}
            label={subagentRailSummary(turn.subagents, turn.ended)}
            onClick={onSeeWhatRan}
          />
        </RailGroup>
      )}
      {backgroundTools.length > 0 && (
        <RailGroup title="Background processes">
          {backgroundTools.map((tool) => (
            <RailRow
              key={tool.callId ?? tool.key}
              label={tool.verb}
              mark={<ToolSurfaceMark kind="background" tone={railToolTone(tool.status)} />}
              meta={tool.status === "ok" ? undefined : railToolStatus(tool.status)}
              onClick={onSeeWhatRan}
            />
          ))}
        </RailGroup>
      )}
      {computerTools.length > 0 && (
        <RailGroup title="Computer Use">
          {computerTools.map((tool) => (
            <RailRow
              key={tool.callId ?? tool.key}
              label={tool.verb}
              mark={<ToolSurfaceMark kind="computer" tone={railToolTone(tool.status)} />}
              meta={tool.status === "ok" ? undefined : railToolStatus(tool.status)}
              onClick={onSeeWhatRan}
            />
          ))}
        </RailGroup>
      )}
      {(integrationSources.length > 0 || sources.length > 0) && (
        <RailGroup
          title="Sources"
          action="+"
          actionLabel="Manage sources"
          onAction={() => navigate("integrations")}
        >
          {integrationSources.map((source) => (
            <RailRow
              key={`integration:${source.id}`}
              label={source.label}
              mark={<IntegrationSourceMark id={source.id} />}
              onClick={() => navigate("integrations")}
            />
          ))}
          {sources.map((source) => (
            <RailRow
              key={attachmentIdentity(source)}
              label={source.name}
              mark={<SourceMark mediaType={source.media_type} />}
              meta={source.size != null ? formatBytes(source.size) : undefined}
              onClick={() => downloadAttachment(source)}
            />
          ))}
          <RailRow
            label="View all"
            mark={<ViewSourcesMark />}
            onClick={() => navigate("integrations")}
            quiet
          />
        </RailGroup>
      )}
      {mobileActions && (
        <details className="mobile-task-actions">
          <summary>Task actions</summary>
          <div>{mobileActions}</div>
        </details>
      )}
      </div>
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

function attachmentIdentity(attachment: ChatAttachment): string {
  return [
    attachment.name,
    attachment.media_type,
    attachment.size ?? "",
    attachment.data,
  ].join("\u0000");
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

function focusableElements(container: HTMLElement): HTMLElement[] {
  return [...container.querySelectorAll<HTMLElement>(
    "a[href], button:not([disabled]), input:not([disabled]), "
    + "select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])",
  )].filter((element) => element.getAttribute("aria-hidden") !== "true");
}
