import { ActivityTimeline } from "@/panels/chat/ActivityTimeline";
import { EmptyChatStart } from "@/panels/chat/EmptyChatStart";
import {
  LiveBubble,
  MessageList,
  PendingBubble,
  StatusOverlays,
} from "@/panels/chat/MessageParts";
import type { ChatAttachment, ChatMessage } from "@/api/types";
import type { Speech } from "@/voice";
import type { ChatAgent, ChatTab } from "@/panels/chat/constants";
import type { NormalizedTurn } from "@/panels/chatTurn";

type Setter<T> = React.Dispatch<React.SetStateAction<T>>;

interface ChatMessagesProps {
  chatTab: ChatTab;
  slideActive: boolean;
  streaming: boolean;
  messages: ChatMessage[];
  visibleMessages: ChatMessage[];
  firstVisibleIndex: number;
  msgsLoading: boolean;
  msgsError: string | null;
  isEmpty: boolean;
  activeAgent: ChatAgent;
  userName: string;
  switchDir: "left" | "right" | "";
  switchCount: number;
  compactedCount: number;
  compacted: boolean;
  setCompacted: Setter<boolean>;
  clearIndex: number | null;
  chatSearchTerm: string;
  pendingUser: string | null;
  pendingAttachments: ChatAttachment[];
  showLive: boolean;
  live: NormalizedTurn;
  selectedAgent: ChatAgent;
  resolvedHitls: Record<string, string>;
  onResolve: (id: string, status: string) => void;
  lastAssistantId: string | null;
  regenerating: string | null;
  onRegenerate: (id: string) => void;
  onOpenRun: (runId: string) => void;
  speech: Speech;
  stopped: boolean;
  streamError: string | null;
  onWatchAgain: () => void;
  onReconnect: () => void;
  showJump: boolean;
  onJumpToLatest: () => void;
  onMessagesScroll: () => void;
  onCycleAgent: (dir: "left" | "right") => void;
  messagesRef: React.RefObject<HTMLDivElement>;
}

function ChatMessagesHeader(props: ChatMessagesProps): JSX.Element {
  const {
    msgsLoading,
    msgsError,
    messages,
    isEmpty,
    activeAgent,
    userName,
    switchDir,
    switchCount,
    compactedCount,
    compacted,
    setCompacted,
    onCycleAgent,
  } = props;

  return (
    <>
      {msgsLoading && messages.length === 0 && <p className="muted chat-statusline">Loading conversation...</p>}
      {msgsError && <p className="error chat-statusline">Failed to load conversation: {msgsError}</p>}
      {isEmpty && (
        <EmptyChatStart
          activeAgent={activeAgent}
          onPrev={() => onCycleAgent("left")}
          onNext={() => onCycleAgent("right")}
          switchDir={switchDir}
          switchCount={switchCount}
          userName={userName}
        />
      )}
      {compactedCount > 0 && !compacted && (
        <button className="chat-compact-line" type="button" onClick={() => setCompacted(true)}>
          {compactedCount} earlier messages collapsed
        </button>
      )}
    </>
  );
}

function ChatMessageStream(props: ChatMessagesProps): JSX.Element {
  const {
    visibleMessages,
    firstVisibleIndex,
    clearIndex,
    activeAgent,
    resolvedHitls,
    onResolve,
    lastAssistantId,
    streaming,
    pendingUser,
    regenerating,
    onRegenerate,
    onOpenRun,
    speech,
    chatSearchTerm,
    msgsLoading,
    pendingAttachments,
    showLive,
    live,
    selectedAgent,
  } = props;

  return (
    <>
      <MessageList
        visibleMessages={visibleMessages}
        firstVisibleIndex={firstVisibleIndex}
        clearIndex={clearIndex}
        activeAgent={activeAgent}
        resolvedHitls={resolvedHitls}
        onResolve={onResolve}
        lastAssistantId={lastAssistantId}
        streaming={streaming}
        pendingUser={pendingUser}
        regenerating={regenerating}
        onRegenerate={onRegenerate}
        onOpenRun={onOpenRun}
        speech={speech}
      />
      {chatSearchTerm.trim() && visibleMessages.length === 0 && !msgsLoading && (
        <p className="muted chat-statusline">No matching messages.</p>
      )}
      {pendingUser !== null && <PendingBubble pendingUser={pendingUser} pendingAttachments={pendingAttachments} />}
      {showLive && (
        <LiveBubble
          live={live}
          selectedAgent={selectedAgent}
          streaming={streaming}
          resolvedHitls={resolvedHitls}
          onResolve={onResolve}
          onOpenRun={onOpenRun}
          speech={speech}
        />
      )}
    </>
  );
}

export function ChatMessages(props: ChatMessagesProps): JSX.Element {
  const { chatTab, messages, live, activeAgent, onOpenRun } = props;

  if (chatTab === "activity") {
    return (
      <div className="chat-stage__activity">
        <ActivityTimeline messages={messages} live={live} activeAgent={activeAgent} onOpenRun={onOpenRun} />
      </div>
    );
  }

  const { slideActive, streaming, stopped, streamError, showJump, onWatchAgain, onReconnect, onJumpToLatest, onMessagesScroll, messagesRef } = props;

  return (
    <div
      className="chat__messages"
      aria-live={slideActive ? "polite" : "off"}
      aria-busy={streaming}
      ref={messagesRef}
      onScroll={onMessagesScroll}
    >
      <ChatMessagesHeader {...props} />
      <ChatMessageStream {...props} />
      <StatusOverlays
        stopped={stopped}
        streamError={streamError}
        liveRunId={live.runId ?? null}
        showJump={showJump}
        onWatchAgain={onWatchAgain}
        onReconnect={onReconnect}
        onJumpToLatest={onJumpToLatest}
      />
    </div>
  );
}

export { type ChatMessagesProps };
