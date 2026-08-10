import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from "react";
import { flushSync } from "react-dom";
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
  type FamiliarPhenotypeResponse,
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
import { ConversationControls } from "./ConversationControls";
import { FamiliarBadge } from "./familiar/FamiliarBadge";
import { FamiliarStage } from "./familiar/FamiliarStage";
import {
  familiarStateFromTurn,
  type FamiliarPresentationMode,
} from "./familiar/FamiliarState";
import { LiveQuestionCard } from "./LiveQuestionCard";
import { MobileChat } from "./MobileChat";
import { VoiceCall } from "./VoiceCall";
import { InlineApproval, SettledApproval } from "./chat/InlineApproval";
import { ModelChip } from "./chat/ModelChip";
import { RunSectionView } from "./chat/RunSectionView";
import { SubagentChips } from "./chat/SubagentChips";
import { SubagentTabs } from "./chat/SubagentTabs";
import { useTechDetails } from "./chat/useTechDetails";
import { VoiceBanner } from "./chat/VoiceBanner";
import { WorkDisclosure } from "./chat/WorkDisclosure";
import "./chat/chat.css";

interface ChatViewProps {
  conversationId: string | null;
  onConversation(id: string): void;
  onChanged(): void;
  /** Mount point for the subagent tab strip (SubagentTabs): subagent chips
      and fan-out rows call this with the subagent whose pane should open
      beside the conversation. Until the tabs surface is wired, the rows stay
      non-interactive rather than pretending a pane exists. */
  onOpenSubagent?(agent: SubagentEntry): void;
}

const DEFAULT_ATTACHMENT_LIMITS: ChatAttachmentLimits = {
  max_count: 8,
  max_bytes: 256 * 1_024,
  max_total_bytes: 1_024 * 1_024,
  model_readable_media_types: ["text/*"],
};

export function ChatView({
  conversationId,
  onConversation,
  onChanged,
  onOpenSubagent,
}: ChatViewProps) {
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
  // Mobile is a different surface, not the console squeezed. Below the phone
  // breakpoint the conversation is drawn by MobileChat on its own palette.
  const phone = useMediaQuery("(max-width: 640px)");
  // The split panes (subagent tabs, run-section drawing) mount only in the
  // desktop layout. Narrower widths keep chips and rail rows as static
  // readings, so no control is offered whose target surface cannot appear.
  const canOpenPanes = !phone && !compactTaskDetails;
  const [mobileDraft, setMobileDraft] = useState("");
  // The composer draft is lifted so starter cards can fill it (the design's
  // New screen behaviour: a starter fills the draft, it never sends).
  const [draft, setDraft] = useState("");
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
  const [phenotype, setPhenotype] = useState<FamiliarPhenotypeResponse | null>(null);
  const [pageHidden, setPageHidden] = useState(
    typeof document !== "undefined" && document.visibilityState === "hidden",
  );
  const [taskDetailsOpen, setTaskDetailsOpen] = useState(false);
  const taskDetailsTriggerRef = useRef<HTMLButtonElement>(null);
  const taskDetailsPanelRef = useRef<HTMLElement>(null);
  const controllersRef = useRef(new Set<AbortController>());
  const selectedConversationRef = useRef<string | null>(conversationId);
  selectedConversationRef.current = conversationId;
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
    // The design's New tab resets the draft on entry; switching conversations
    // likewise drops a stale draft rather than carrying it across tasks.
    setDraft("");
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
        // The selection may have moved again while this load was in flight;
        // never attach a follow stream for a conversation no longer shown.
        if (selectedConversationRef.current !== conversationId) return;
        if (
          thread.active_run_id
          && !ownsLiveStream
          && controllersRef.current.size === 0
        ) {
          activeRunRef.current = thread.active_run_id;
          void reattach(conversationId, 0, true);
        }
      })
      .catch((reason) => {
        if (selectedConversationRef.current !== conversationId) return;
        setError(reasonText(reason));
      });
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
        sawStreamEvent = true;
        acceptLiveEvent(event);
      }, controller.signal);
      if (queued) {
        activeRunRef.current = queued.run_id;
        liveConversationRef.current = queued.conversation_id;
        setContinuity("Instruction queued behind the active turn.");
        // A 202 queue receipt carries no stream. When no other stream is
        // open (the active turn was started elsewhere or the local follow
        // already dropped), attach a follow after this send's controller is
        // released, or the live turn and the queued turn are both invisible.
        if (controllersRef.current.size === 1) {
          followQueuedId = queued.conversation_id;
        }
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
      if (followQueuedId) void reattach(followQueuedId, 0, true);
    }
  }

  async function stop() {
    const runId = activeRunRef.current ?? live.runId;
    abortStreams();
    try {
      if (runId) await client.cancelRun(runId);
      activeRunRef.current = null;
      liveConversationRef.current = null;
      setContinuity("");
      setRetryFollow(false);
      if (conversationId) {
        await loadConversation(conversationId);
        setEvents([]);
      }
    } catch (reason) {
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

  async function loadConversation(id: string) {
    const [thread, artifactResult, list] = await Promise.all([
      client.conversation(id),
      client.artifacts({ conversationId: id, limit: 25 }).catch(() => ({
        artifacts: [] as Artifact[],
        next_cursor: null,
      })),
      client.conversations().catch(() => ({ conversations: [] })),
    ]);
    // A slow load must not clobber the view once the selection has moved on;
    // callers still receive the thread for their own bookkeeping.
    if (selectedConversationRef.current !== id) return thread;
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

  // One Familiar Stage per client (ADR 0025), placed where the being presides:
  // large and centred over the hero welcome; as the avatar bullet of the most
  // recent assistant turn once the conversation has content (older turns keep
  // static badges); back to the centre, large, for the whole life of a voice
  // call; minimised sizing while the tab is hidden. Conditional rendering
  // guarantees a single renderer session; each move is a remount by design
  // (the being re-arrives through its aperture in the new position).
  const stageIsHero = messages.length === 0 && events.length === 0;
  const stagePlacement: "hero" | "centre" | "bullet" = callActive
    ? "centre"
    : stageIsHero
      ? "hero"
      : "bullet";
  const stageMode: FamiliarPresentationMode = pageHidden
    ? "minimised"
    : callActive
      ? "voice"
      : stageIsHero
        ? "hero"
        : "conversation";
  const stageState = familiarStateFromTurn({
    loading,
    hasLiveEvents: events.length > 0,
    liveEnded: live.ended,
    voiceSpeaking: voiceActivity.speaking,
    voiceLevel: voiceActivity.level,
    voiceBands: voiceActivity.bands ?? null,
    voiceOnset: voiceActivity.onset,
  });
  const stage = <FamiliarStage mode={stageMode} state={stageState} phenotype={phenotype} />;
  const bulletStage = stagePlacement === "bullet" ? stage : undefined;

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
    for (const message of messages) {
      if (!message.events?.length) continue;
      for (const agent of normalizeEvents(message.events).subagents) {
        seen.add(agent.childRunId || agent.key);
      }
    }
    for (const agent of live.subagents) seen.add(agent.childRunId || agent.key);
    return seen.size;
  }, [messages, live]);

  // Live voice is feature-guarded the same way VoiceCall guards itself: the
  // affordances render only where the call control is actually mounted.
  const voiceAvailable = (
    typeof client.createCall === "function"
    && (!conversationId || conversationStatus === "active")
  );

  // The empty-draft primary and the voice banner both start the call through
  // the mounted VoiceCall control (its start button inside the dock), so call
  // creation, capability fallbacks and media teardown stay in one place.
  function startVoiceFromComposer() {
    const dock = voiceDockRef.current;
    const buttons = dock ? [...dock.querySelectorAll("button")] : [];
    const start = dock?.querySelector<HTMLButtonElement>(
      ".voice-idle > button.secondary-button",
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
        <MobileChat
          busy={Boolean(live.runId) && !live.ended}
          composerValue={mobileDraft}
          messages={messages}
          onBack={() => navigate("home")}
          onComposerChange={setMobileDraft}
          onRespondHitl={async (id, decision) => {
            try {
              const result = await client.respondHitl(id, decision, "");
              return result.status === "ok" || result.status === "answered";
            } catch {
              return false;
            }
          }}
          onSend={() => {
            const text = mobileDraft.trim();
            if (!text) return;
            setMobileDraft("");
            void send(text, []);
          }}
          subtitle={live.subagents.length > 0
            ? `${live.subagents.length} working`
            : conversationStatus === "closed" ? "Closed" : ""}
          title={conversationId ? (conversationTitle || "Untitled task") : "New chat"}
          turn={live}
        />
        {taskDetailsOpen && (
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
          compact
          open={taskDetailsOpen}
          panelRef={taskDetailsPanelRef}
          onClose={closeTaskDetails}
          onConversationDeleted={() => {
            closeTaskDetails();
            void controlsChanged().catch((reason) => setError(reasonText(reason)));
          }}
        />
      </>
    );
  }

  return (
    <>
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
      data-rail-collapsed={!compactTaskDetails && !railOpen ? "true" : undefined}
      style={sectionRunId ? { display: "none" } : undefined}
    >
      <main className="chat-main">
        {showHeader ? (
        <header className="chat-header">
          <div className="agent-heading">
            <h1>{
              conversationStatus === "closed"
                ? "Closed conversation"
                : conversationId
                  ? (conversationTitle || "Untitled task")
                  : "New chat"
            }</h1>
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
        ) : (
          // Chrome-free New state: the theme control floats where the header
          // actions would sit, so the surface keeps its one theme affordance.
          <div className="chat-floating-actions"><ThemeToggle /></div>
        )}
        {stagePlacement === "centre" && (
          <div className="voice-stage" aria-hidden={false}>{stage}</div>
        )}
        <div
          aria-label="Conversation transcript"
          aria-live="polite"
          className="transcript"
          role="region"
          tabIndex={0}
        >
          {stageIsHero ? <Welcome onStarter={fillDraft} /> : null}
          {messages.map((message) => (
            <Message
              key={message.id}
              message={message}
              stage={events.length === 0 && message.id === lastAssistantMessageId
                ? bulletStage
                : undefined}
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
              turn={live}
              stage={bulletStage}
              tech={tech}
              startedAt={live.runId ? liveStartsRef.current.get(live.runId) ?? null : null}
              onOpenSubagent={canOpenPanes ? openSubagentTab : undefined}
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
        {isNewState && voiceAvailable && (
          <VoiceBanner onStartVoice={startVoiceFromComposer} />
        )}
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
          value={draft}
          onChange={setDraft}
          inputRef={draftInputRef}
          tech={tech}
          voicePrimary={isNewState && voiceAvailable && !callActive
            ? { onStart: startVoiceFromComposer }
            : undefined}
          voice={(!conversationId || conversationStatus === "active") ? (
            <span className="voice-dock" ref={voiceDockRef}>
              <VoiceCall
                conversationId={conversationId}
                modelProfileId={profile || undefined}
                onConversation={onConversation}
                onError={setError}
                onFamiliarActivity={setVoiceActivity}
                onCallActive={setCallActive}
              />
            </span>
          ) : undefined}
        />
        {isNewState && voiceAvailable && !callActive && !draft.trim() && (
          <p className="composer-hint">
            Nothing typed, so the round button starts a voice call.
          </p>
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
        onOpenSubagent={canOpenPanes ? openSubagentTab : undefined}
        onSeeWhatRan={canOpenPanes && live.runId
          ? () => setSectionRunId(live.runId ?? null)
          : undefined}
        compact={compactTaskDetails}
        open={compactTaskDetails ? taskDetailsOpen : railOpen}
        panelRef={taskDetailsPanelRef}
        onClose={closeTaskDetails}
        onConversationDeleted={() => {
          closeTaskDetails();
          void controlsChanged().catch((reason) => setError(reasonText(reason)));
        }}
      />
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
function Welcome({ onStarter }: { onStarter?(text: string): void }) {
  return (
    <section className="welcome">
      <svg className="welcome-glyph" viewBox="0 0 24 24" width="42" height="42" fill="none" aria-hidden>
        <path d="M7.5 3.5H4.5V20.5H7.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        <path d="M16.5 3.5H19.5V20.5H16.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        <path d="M13.2 4.8L8.8 12.4H12L10.9 19.2L15.3 11.6H12.1L13.2 4.8Z" fill="currentColor" />
      </svg>
      <h2>What needs doing?</h2>
      <div className="starters">
        {STARTERS.map(({ title, desc, icon }) => (
          <button
            className="starter-card"
            key={title}
            onClick={() => onStarter?.(title)}
            type="button"
          >
            <span aria-hidden className="starter-icon">
              <svg fill="none" height="16" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" viewBox="0 0 24 24" width="16">
                {icon.map((d) => <path d={d} key={d} />)}
              </svg>
            </span>
            <span className="starter-title">{title}</span>
            <span className="starter-desc">{desc}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

function Message({
  message,
  stage,
  tech,
  durationSeconds,
  onOpenSubagent,
}: {
  message: ChatMessage;
  // The one Familiar Stage, when this is the newest assistant turn it
  // presides over (ADR 0025); older turns render the static badge.
  stage?: React.ReactNode;
  tech: boolean;
  durationSeconds?: number;
  onOpenSubagent?(agent: SubagentEntry): void;
}) {
  const turn = useMemo(() => normalizeEvents(message.events ?? []), [message.events]);
  const identity = turn.subagents[0];
  return (
    <article className={`message ${message.role}`}>
      {message.role === "assistant" && (
        <div className="message-author">
          {stage ?? (
            <FamiliarBadge
              state={turn.ended ? "ready" : "working"}
              genotype={identity?.familiarGenotype}
              label={identity?.name}
            />
          )}
          <strong>{identity?.name ?? "Boltrig"}</strong>
        </div>
      )}
      <div className="message-content">
        {turn.degraded && (
          <p className="notice" role="status">
            This response used a degraded fallback; treat its result as incomplete.
          </p>
        )}
        {/* The design's order: the collapsed work disclosure sits above the
            prose, subagents and decisions below it. */}
        {message.events?.length ? (
          <WorkDisclosure turn={turn} settled durationSeconds={durationSeconds ?? null} />
        ) : null}
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
        {message.events?.length ? (
          <TurnDecisions turn={turn} settled tech={tech} onOpenSubagent={onOpenSubagent} />
        ) : null}
      </div>
    </article>
  );
}

function LiveTurn({
  turn,
  stage,
  tech,
  startedAt,
  onOpenSubagent,
}: {
  turn: NormalizedTurn;
  stage?: React.ReactNode;
  tech: boolean;
  startedAt: number | null;
  onOpenSubagent?(agent: SubagentEntry): void;
}) {
  const identity = turn.subagents[0];
  return (
    <article className="message assistant live">
      <div className="message-author">
        {stage ?? (
          <FamiliarBadge
            state={turn.ended ? "ready" : "working"}
            genotype={identity?.familiarGenotype}
            label={identity?.name}
          />
        )}
        <strong>{identity?.name ?? "Boltrig"}</strong>
      </div>
      <div className="message-content">
        {turn.degraded && (
          <p className="notice" role="status">
            This response used a degraded fallback; treat its result as incomplete.
          </p>
        )}
        {turn.reasoning && <details><summary>Working notes</summary><p>{turn.reasoning}</p></details>}
        <WorkDisclosure turn={turn} startedAt={startedAt} />
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{turn.text || "Working…"}</ReactMarkdown>
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

/** Everything below the prose: the subagent chip row and fan-out, then the
 * decision cards (approvals and questions) in stream order. Tool activity is
 * not repeated here - it lives in the WorkDisclosure above the prose. */
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

interface ComposerProps {
  busy: boolean;
  disabled: boolean;
  closed: boolean;
  profiles: ModelProfile[];
  profile: string;
  attachmentLimits: ChatAttachmentLimits;
  attachmentLimitsVerified: boolean;
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
}

function Composer({
  busy,
  disabled,
  closed,
  profiles,
  profile,
  attachmentLimits,
  attachmentLimitsVerified,
  value,
  onChange,
  inputRef,
  tech,
  voicePrimary,
  onProfile,
  onSend,
  onStop,
  voice,
}: ComposerProps) {
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
    onChange("");
    const sentFiles = files;
    setFiles([]);
    const restore = await onSend(message, sentFiles);
    if (restore) {
      onChange((current) => current || message);
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
          <button type="button" className="icon-button" disabled={disabled} onClick={() => input.current?.click()} aria-label="Attach files">＋</button>
          {voice}
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
      <p className="muted small">
        Text files are included in the model task. Other file types are recorded
        with the conversation but are not read by the model.
        {!attachmentLimitsVerified && " Server limits will be checked when you send."}
      </p>
    </form>
  );
}

// A rail group: a header line carrying a title and at most one verb, then its
// rows. The seam between groups is drawn by `.rail-group + .rail-group`, so a
// group never draws its own border and the rail stays one card.
function RailGroup({
  title,
  action,
  onAction,
  children,
}: {
  title: string;
  action?: string;
  onAction?(): void;
  children: React.ReactNode;
}) {
  return (
    <div className="rail-group">
      <div className="rail-group-head">
        <span>{title}</span>
        {action !== undefined && (
          onAction
            ? <button className="rail-action" onClick={onAction} type="button">{action}</button>
            : <span className="rail-action" aria-hidden={false}>{action}</span>
        )}
      </div>
      {children}
    </div>
  );
}

function RailRow({
  tone,
  mark,
  label,
  meta,
  quiet,
  onClick,
}: {
  tone?: "green" | "amber" | "red" | "unknown";
  mark?: React.ReactNode;
  label: string;
  meta?: string;
  quiet?: boolean;
  onClick?(): void;
}) {
  const inner = (
    <>
      {mark
        ? <span className="rail-mark">{mark}</span>
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
  onOpenSubagent?(agent: SubagentEntry): void;
  /** Opens the run-section drawing; offered only while the turn has a run. */
  onSeeWhatRan?(): void;
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
  onOpenSubagent,
  onSeeWhatRan,
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
      <div className="rail-card">
      <RailGroup
        title="This run"
        action={turn.runId && onSeeWhatRan ? "See what ran" : undefined}
        onAction={turn.runId ? onSeeWhatRan : undefined}
      >
        <RailRow
          tone={turn.cancelled ? "red" : turn.ended ? "green" : turn.runId ? "green" : "unknown"}
          label={turn.cancelled ? "Cancelled" : turn.ended ? "Done" : turn.runId ? "Running" : "Ready"}
          meta={turn.runId ? turn.runId.slice(0, 10) : "—"}
        />
        <RailRow
          tone="unknown"
          quiet
          label={`${turn.tools.length} ${turn.tools.length === 1 ? "tool" : "tools"}`}
          meta={`${turn.subagents.length} ${turn.subagents.length === 1 ? "subagent" : "subagents"}`}
        />
      </RailGroup>
      {(turn.hitls.length > 0 || turn.questions.length > 0) && (
        <RailGroup title="Waiting for you" action={String(turn.hitls.length + turn.questions.length)}>
          {turn.hitls.map((item) => (
            <RailRow key={item.hitlRequestId} tone="amber" label={item.question} meta={item.verb} />
          ))}
          {turn.questions.map((item) => (
            <RailRow key={item.questionId} tone="amber" label={item.prompt} />
          ))}
        </RailGroup>
      )}
      {turn.subagents.length > 0 && (
        <RailGroup title="Subagents">
          {turn.subagents.map((item) => (
            <RailRow
              key={item.key}
              quiet
              mark={<FamiliarBadge state={turn.ended ? "ready" : "working"} label={item.name ?? item.task} />}
              label={item.name ?? item.task}
              meta={item.role}
              onClick={onOpenSubagent ? () => onOpenSubagent(item) : undefined}
            />
          ))}
        </RailGroup>
      )}
      <RailGroup title="Artifacts">
      <div className="rail-body">
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
      </div>
      </RailGroup>
      {conversation && (
        <div className="rail-group">
          <ConversationControls
            conversationId={conversation.id}
            title={conversation.title}
            status={conversation.status}
            lastAssistantMessageId={conversation.lastAssistantMessageId}
            onChanged={() => void onConversationChanged()}
            onDeleted={onConversationDeleted}
          />
        </div>
      )}
      <div className="rail-group privacy-note">
        <span aria-hidden>◇</span>
        <p><strong>Governed by Boltrig</strong>Tools, credentials, memory, and approvals stay server-side.</p>
      </div>
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
