import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import {
  BoltrigApiError,
  type Artifact,
  type ChatAttachment,
  type ChatEvent,
  type ChatMessage,
  type ConversationModelContext,
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
import { FamiliarBadge } from "./familiar/FamiliarBadge";
import { StageBody, useFamiliarBody, type StageTurnInput } from "./StageBody";
import { useCharacter } from "./characters";
import { familiarStateFromTurn } from "./familiar/FamiliarState";
import { MobileChat } from "./MobileChat";
import { VoiceCall } from "./VoiceCall";
import { Composer } from "./chat/Composer";
import { LiveTurn, Message } from "./chat/ChatMessages";
import { ComposerRunStatus } from "./chat/QueuedMessages";
import { RunSectionView } from "./chat/RunSectionView";
import { RoutineRunBanner, useConversationProvenance } from "./chat/RoutineRunBanner";
import { SubagentTabs } from "./chat/SubagentTabs";
import { TaskInspector } from "./chat/TaskInspector";
import type {
  TaskInspectorOutput,
  TaskInspectorSource,
} from "./chat/TaskInspectorModel";
import { ThemeToggle } from "./chat/ThemeToggle";
import { TranscriptNavigation } from "./chat/TranscriptNavigation";
import { VoiceBanner } from "./chat/VoiceBanner";
import { Welcome } from "./chat/Welcome";
import { downloadAttachment } from "./chat/attachmentPresentation";
import { reasonText } from "./chat/chatErrors";
import { useChatModelOptions } from "./chat/useChatModelOptions";
import { useChatProjection } from "./chat/useChatProjection";
import { useConversationQueue } from "./chat/useConversationQueue";
import { useLiveReplySpeech } from "./chat/useReplySpeech";
import { useStagePhenotype } from "./chat/useStagePhenotype";
import { useTechDetails } from "./chat/useTechDetails";
import { useTranscriptViewport } from "./chat/useTranscriptViewport";
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
  /** Opens the existing governed command/search surface. An empty composer
      uses this for slash discovery instead of growing a second command store. */
  onCommandPalette?(): void;
}

type ConversationLoadState = { conversationId: string | null;
  phase: "idle" | "loading" | "ready" | "error"; error: string;
};

export function ChatView({
  conversationId,
  onConversation,
  onChanged,
  onWorkingChange,
  onOpenSubagent,
  onCommandPalette,
}: ChatViewProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [events, setEvents] = useState<ChatEvent[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [artifactCursor, setArtifactCursor] = useState<string | null>(null);
  const [loadingArtifacts, setLoadingArtifacts] = useState(false);
  const {
    attachmentLimits,
    defaultModelAvailable,
    defaultModelName,
    defaultModelSource,
    defaultModelUnavailableReason,
    modelChoice,
    modelChoices,
    modelChoicesLoaded,
    setModelChoice,
  } = useChatModelOptions();
  const [conversationTitle, setConversationTitle] = useState("");
  const [conversationStatus, setConversationStatus] = useState("");
  const conversationProvenance = useConversationProvenance();
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
  const compactTaskDetails = useMediaQuery("(max-width: 1374px)");
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
  // Queued steers are durable user messages with no run id yet. Keep a small
  // local echo so the row appears as soon as the 202 receipt arrives; the next
  // conversation load reconciles it with the append-only message log.
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
  const voiceDockRef = useRef<HTMLSpanElement>(null);
  const tech = useTechDetails();
  const [voiceActivity, setVoiceActivity] = useState<{
    speaking: boolean;
    level: number;
    bands?: number[];
    onset?: number;
  }>({ speaking: false, level: 0 });
  const [callActive, setCallActive] = useState(false);
  const selectedCharacterId = useFamiliarBody();
  const selectedCharacter = useCharacter(selectedCharacterId);
  const { phenotype } = useStagePhenotype(
    selectedCharacter.readsPhenotype && !callActive,
  );
  const [taskDetailsOpen, setTaskDetailsOpen] = useState(false);
  const taskDetailsTriggerRef = useRef<HTMLButtonElement>(null);
  const railToggleRef = useRef<HTMLButtonElement>(null);
  const taskDetailsPanelRef = useRef<HTMLElement>(null);
  const previousCompactTaskDetailsRef = useRef(compactTaskDetails);
  const [inspectorOutputError, setInspectorOutputError] = useState("");
  const [materializedOutputs, setMaterializedOutputs] = useState<Record<string, string>>({});
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
  const queue = useConversationQueue({ conversationId, generationRef: conversationGenerationRef,
    selectedRef: selectedConversationRef, reload: loadConversation, setContinuity, setError });
  const {
    conversationSubagentCount,
    inspectorModel,
    live,
    materializedOutputIds,
    queuedMessages,
    railTurn,
    railTurnIsLive,
    sources,
    transcriptMessages,
    transcriptRevision,
  } = useChatProjection({
    artifacts,
    consumedSteerIds: queue.consumedIds,
    continuity,
    error,
    events,
    localQueuedMessages: queue.localMessages,
    materializedOutputs,
    messages,
    queuedMessageOrder: queue.order,
  });
  const transcriptViewport = useTranscriptViewport({
    conversationKey: conversationId,
    contentRevision: transcriptRevision,
  });
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

  const primeReplySpeech = useLiveReplySpeech({ callActive, conversationKey: conversationId, live, onActivity: setVoiceActivity, onError: setError });
  // Reset route-owned projections before paint while retaining an adopted live stream.
  useLayoutEffect(() => {
    const ownsLiveStream = Boolean(
      conversationId
      && liveConversationRef.current === conversationId
      && controllersRef.current.size > 0
    );

    // Adopt a stream-created conversation; every other selection is a hard boundary.
    if (!ownsLiveStream) conversationGenerationRef.current += 1;
    // Model selection is a per-conversation next-turn choice. Never carry an
    // explicit route from task A into task B. The null -> newly-created route
    // adoption above deliberately preserves the choice that started its live
    // turn, so the locked label remains truthful until that turn settles.
    if (!ownsLiveStream) setModelChoice("");

    setError("");
    setContinuity("");
    setRetryFollow(false);
    // New and switched tasks drop stale drafts.
    setDraft("");
    queue.reset();
    setMessages([]);
    setArtifacts([]);
    setArtifactCursor(null);
    setLoadingArtifacts(false);
    setInspectorOutputError("");
    setMaterializedOutputs({});
    setConversationTitle("");
    setConversationStatus("");
    conversationProvenance.clear();
    setModelContext(null);
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
    const wasCompact = previousCompactTaskDetailsRef.current;
    previousCompactTaskDetailsRef.current = compactTaskDetails;
    if (!wasCompact || compactTaskDetails) return;
    const sheetWasOpen = taskDetailsOpen;
    setTaskDetailsOpen(false);
    if (!sheetWasOpen) return;
    // The compact trigger has just unmounted and this effect runs after the
    // desktop toggle commits. Make that visible control the return target
    // instead of leaving focus on <body>.
    railToggleRef.current?.focus();
  }, [compactTaskDetails, taskDetailsOpen]);

  async function send(
    message: string,
    attachments: ChatAttachment[],
  ): Promise<boolean> {
    const selectedModelAvailable = modelChoice
      ? modelChoices.some((choice) => choice.id === modelChoice && choice.available)
      : defaultModelAvailable;
    if (!modelChoicesLoaded || !selectedModelAvailable) {
      setError("Choose an available model in the composer before sending.");
      return true;
    }
    if (conversationId && conversationStatus !== "active") {
      setError(
        conversationStatus === "closed"
          ? "Restore this conversation before adding another turn."
          : "Wait for the conversation state to finish loading.",
      );
      return true;
    }
    primeReplySpeech();
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
        // A queued steer joins the already-admitted turn and therefore
        // inherits its locked model. Sending the choice again would pretend a
        // mid-turn switch is possible and the server correctly rejects it.
        ...(!joiningActiveTurn && modelChoice
          ? { model_choice_id: modelChoice }
          : {}),
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
        queue.echo({
          id: queuedMessageId,
          role: "user",
          content: message,
          attachments,
          created_at: new Date().toISOString(),
        });
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
          setContinuity("Live updates paused. The run is still continuing safely.");
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
    queue.hydrate(thread.queued_message_ids ?? [], loadedMessageIds);
    setMessages(thread.messages);
    setModelContext(thread.model_context ?? null);
    setArtifacts(artifactResult.artifacts);
    setArtifactCursor(artifactResult.next_cursor ?? null);
    setConversationTitle(summary.title || "Untitled task");
    setConversationStatus(summary.status);
    conversationProvenance.load(thread, summary);
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

  async function downloadInspectorOutput(output: TaskInspectorOutput) {
    const artifact = artifacts.find((candidate) => candidate.id === output.id);
    if (!artifact) {
      setInspectorOutputError("That output is no longer available. Refresh the task and retry.");
      return;
    }
    const owner = conversationId;
    setInspectorOutputError("");
    try {
      const bytes = await client.downloadArtifact(artifact.id);
      if (selectedConversationRef.current !== owner) return;
      const result = await materializeArtifact(artifact.name, bytes);
      if (selectedConversationRef.current !== owner) return;
      if (result.status === "saved") {
        setMaterializedOutputs((current) => ({
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
      if (selectedConversationRef.current === owner) {
        setInspectorOutputError("The output could not be downloaded. It is safe to retry.");
      }
    }
  }

  async function useMaterializedInspectorOutput(
    output: TaskInspectorOutput,
    action: (handle: string) => Promise<void>,
  ) {
    const handle = materializedOutputs[output.id];
    if (!handle) return;
    const owner = conversationId;
    setInspectorOutputError("");
    try {
      await action(handle);
    } catch {
      if (selectedConversationRef.current !== owner) return;
      setInspectorOutputError(
        `The saved copy of ${output.name} is no longer available. Save it again.`,
      );
      setMaterializedOutputs((current) => {
        const next = { ...current };
        delete next[output.id];
        return next;
      });
    }
  }

  function selectInspectorSource(source: TaskInspectorSource) {
    if (source.kind === "integration") {
      navigate("integrations");
      return;
    }
    const attachment = sources[source.attachmentIndex];
    if (attachment) downloadAttachment(attachment);
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
        queue.consume(event.message_id);
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

  // One Familiar Stage per client (ADR 0025). The new-chat invitation uses a
  // compact preview; once voice starts, VoiceCall's portalled modal owns the
  // one full-resolution Stage. Chat must not leave a second WebGL renderer
  // running invisibly behind that modal.
  const stageIsHero = messages.length === 0 && events.length === 0;
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

  // The decided target's New screen is chrome-free: no header row, the glyph
  // and question are the top of the surface. A conversation (or a live call)
  // brings the header back.
  const isNewState = stageIsHero && !conversationId;
  const showHeader = !isNewState || callActive;

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

  function promptForOutput() {
    const seed = "Create a file or site";
    setDraft((current) => current.trim() ? current : seed);
    if (compactTaskDetails) setTaskDetailsOpen(false);
    window.setTimeout(() => {
      if (phone) {
        document.querySelector<HTMLTextAreaElement>(".m-composer .m-input")?.focus();
      } else {
        draftInputRef.current?.focus();
      }
    }, 0);
  }

  const composer = (
    <Composer
      busy={loading}
      disabled={Boolean(conversationId) && (!conversationReady || conversationStatus !== "active")}
      closed={conversationStatus === "closed"}
      conversationKey={conversationId}
      modelChoices={modelChoices}
      modelChoice={modelChoice}
      defaultModelName={defaultModelName}
      defaultModelSource={defaultModelSource}
      defaultModelAvailable={defaultModelAvailable}
      defaultModelUnavailableReason={defaultModelUnavailableReason}
      modelChoicesLoaded={modelChoicesLoaded}
      modelSelectionLocked={loading || (Boolean(live.runId) && !live.ended)}
      attachmentLimits={attachmentLimits}
      onModelChoice={setModelChoice}
      onSend={send}
      onStop={stop}
      value={draft}
      onChange={setDraft}
      inputRef={draftInputRef}
      newContext={isNewState}
      unavailable={Boolean(conversationLoadError)}
      onCommandPalette={onCommandPalette}
      voicePrimary={voiceAvailable && !callActive
        ? { onStart: startVoiceFromComposer }
        : undefined}
      voice={(!conversationId || conversationStatus === "active") ? (
        <span className="voice-dock" ref={voiceDockRef}>
          <VoiceCall
            conversationId={conversationId}
            conversationTitle={conversationTitle || undefined}
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
  const newChatPrompt = (
    <div className="new-chat-prompt-stack">
      {!callActive && voiceAvailable && (
        <VoiceBanner
          companionName={selectedCharacter.name}
          identity={(
            <StageBody
              input={stageInput}
              label="chief of staff"
              mode="conversation"
              phenotype={phenotype}
              turn={live}
            />
          )}
          onStartVoice={startVoiceFromComposer}
        />
      )}
      {composer}
    </div>
  );

  // Tabs render live entries while their turn is still the live turn (status
  // words keep updating); after it settles, the snapshot taken at open keeps
  // each tab readable. The runId tag stops a later turn's colliding key from
  // substituting its own, unrelated entry.
  const tabAgents = openTabs.map((tab) =>
    (live.runId === tabsRunId
      ? live.subagents.find((entry) => entry.key === tab.key)
      : undefined) ?? tab.agent);

  if (phone) {
    // The mobile surface replaces the console conversation, not the chat
    // contract: the task-details sheet (artifacts, run facts, conversation
    // controls) stays reachable through the same trigger/scrim/inert cycle
    // the compact console uses.
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
          onDecisionResolved={retryConversationLoad}
          onReorderQueued={queue.reorder}
          onRespondHitl={async (id, decision) => {
            try {
              const result = await client.respondHitl(id, decision, "");
              const accepted = result.status === "ok" || result.status === "answered";
              if (accepted) retryConversationLoad();
              return accepted;
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
              document.querySelector<HTMLTextAreaElement>(".m-composer .m-input")?.focus();
            }, 0);
          }}
          onStop={() => void stop()}
          queueReordering={queue.reordering}
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
        {!isNewState && conversationReady && <TaskInspector
          key={`rail:${conversationId ?? "new"}`}
          model={inspectorModel}
          mode="sheet"
          open={taskDetailsOpen}
          panelRef={taskDetailsPanelRef}
          returnFocusRef={taskDetailsTriggerRef}
          hasMoreOutputs={Boolean(artifactCursor)}
          materializedOutputIds={materializedOutputIds}
          outputError={inspectorOutputError}
          outputsLoading={loadingArtifacts}
          onClose={closeTaskDetails}
          onCreateOutput={conversationStatus === "closed" ? undefined : promptForOutput}
          onLoadMoreOutputs={() => void loadMoreArtifacts()}
          onManageSources={() => navigate("integrations")}
          onOpenOutput={(output) => void useMaterializedInspectorOutput(
            output,
            openMaterializedArtifact,
          )}
          onRevealOutput={(output) => void useMaterializedInspectorOutput(
            output,
            revealMaterializedArtifact,
          )}
          onSelectOutput={(output) => void downloadInspectorOutput(output)}
          onSelectSource={selectInspectorSource}
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
          onClick={() => setTaskDetailsOpen((open) => !open)}
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
                ref={railToggleRef}
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
        <div
          aria-label="Conversation transcript"
          className={isNewState ? "transcript new-chat-transcript" : "transcript"}
          id="worker-conversation-transcript"
          onScroll={transcriptViewport.onTranscriptScroll}
          ref={transcriptViewport.transcriptRef}
          role="region"
          tabIndex={0}
        >
          {isNewState ? (
            <Welcome>{newChatPrompt}</Welcome>
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
          <RoutineRunBanner provenance={conversationProvenance.value} />
          {transcriptMessages.map((message) => (
            <Message
              key={message.id}
              message={message}
              tech={tech}
              onDecisionResolved={retryConversationLoad}
              durationSeconds={message.run_id ? turnDurations[message.run_id] : undefined}
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
        {!isNewState && (
          <TranscriptNavigation
            model={transcriptViewport.navigation}
            transcriptId="worker-conversation-transcript"
          />
        )}
        {!isNewState && <ComposerRunStatus
          disabled={queue.reordering}
          messages={queuedMessages}
          steps={live.steps}
          onReorder={queue.reorder}
          onSteer={(message) => {
            setDraft(message.content ?? "");
            setContinuity("Queued instruction loaded into the composer.");
            window.setTimeout(() => draftInputRef.current?.focus(), 0);
          }}
        />}
        {!isNewState && composer}
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
      {!isNewState && conversationReady && <TaskInspector
        key={`rail:${conversationId ?? "new"}`}
        model={inspectorModel}
        mode={compactTaskDetails ? "overlay" : "rail"}
        open={compactTaskDetails ? taskDetailsOpen : railOpen}
        panelRef={taskDetailsPanelRef}
        returnFocusRef={taskDetailsTriggerRef}
        hasMoreOutputs={Boolean(artifactCursor)}
        materializedOutputIds={materializedOutputIds}
        outputError={inspectorOutputError}
        outputsLoading={loadingArtifacts}
        onClose={closeTaskDetails}
        onCreateOutput={conversationStatus === "closed" ? undefined : promptForOutput}
        onInspectRun={canOpenPanes && railTurn.runId
          ? () => setSectionRunId(railTurn.runId ?? null)
          : undefined}
        onLoadMoreOutputs={() => void loadMoreArtifacts()}
        onManageSources={() => navigate("integrations")}
        onOpenOutput={(output) => void useMaterializedInspectorOutput(
          output,
          openMaterializedArtifact,
        )}
        onOpenSubagents={canOpenPanes && railTurn.runId
          ? () => setSectionRunId(railTurn.runId ?? null)
          : undefined}
        onRevealOutput={(output) => void useMaterializedInspectorOutput(
          output,
          revealMaterializedArtifact,
        )}
        onSelectActivity={canOpenPanes && railTurn.runId
          ? () => setSectionRunId(railTurn.runId ?? null)
          : undefined}
        onSelectOutput={(output) => void downloadInspectorOutput(output)}
        onSelectSource={selectInspectorSource}
      />}
    </div>
    </>
  );
}
