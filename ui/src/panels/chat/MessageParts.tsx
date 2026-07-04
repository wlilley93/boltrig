import { Fragment } from "react";

import type { ChatAttachment, ChatMessage } from "@/api/types";
import type { Speech } from "@/voice";
import { AgentAvatar } from "@/panels/chat/AgentAvatar";
import { CopyButton } from "@/panels/chat/CopyButton";
import type { ChatAgent } from "@/panels/chat/constants";
import { Icon } from "@/panels/chat/icons";
import { MarkdownText } from "@/panels/chat/markdown";
import { MessageBubble } from "@/panels/chat/MessageBubble";
import { SpeakButton } from "@/panels/chat/SpeakButton";
import type { NormalizedTurn } from "@/panels/chatTurn";
import { TurnExtras } from "@/panels/chatTurn";

interface MessageListProps {
  visibleMessages: ChatMessage[];
  firstVisibleIndex: number;
  clearIndex: number | null;
  activeAgent: ChatAgent;
  resolvedHitls: Record<string, string>;
  onResolve: (id: string, status: string) => void;
  lastAssistantId: string | null;
  streaming: boolean;
  pendingUser: string | null;
  regenerating: string | null;
  onRegenerate: (id: string) => void;
  onOpenRun: (runId: string) => void;
  speech: Speech;
}

export function MessageList({
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
}: MessageListProps): JSX.Element {
  return (
    <>
      {visibleMessages.map((m, i) => {
        const realIndex = firstVisibleIndex + i;
        return (
          <Fragment key={m.id}>
            {clearIndex === realIndex && (
              <div className="chat-clear-line">
                <span>cleared, scroll up for history</span>
              </div>
            )}
            <MessageBubble
              message={m}
              agent={activeAgent}
              resolvedHitls={resolvedHitls}
              onResolve={onResolve}
              canRegenerate={m.id === lastAssistantId && !streaming && pendingUser === null}
              regenerating={regenerating === m.id}
              onRegenerate={() => onRegenerate(m.id)}
              onOpenRun={onOpenRun}
              speech={speech}
            />
          </Fragment>
        );
      })}
    </>
  );
}

interface PendingBubbleProps {
  pendingUser: string;
  pendingAttachments: ChatAttachment[];
}

export function PendingBubble({ pendingUser, pendingAttachments }: PendingBubbleProps): JSX.Element {
  return (
    <div className="chat-msg chat-msg--user">
      <div className="chat-msg__bubble">
        {pendingUser && <MarkdownText value={pendingUser} />}
        <PendingAttachments attachments={pendingAttachments} />
        <div className="chat-msg__meta">
          <span>sending</span>
          {pendingUser && <CopyButton text={pendingUser} label="Copy" className="chat-msg__action" />}
        </div>
      </div>
    </div>
  );
}

function PendingAttachments({ attachments }: { attachments: ChatAttachment[] }): JSX.Element | null {
  if (!attachments || attachments.length === 0) return null;
  return (
    <div className="chat-atts">
      {attachments.map((a, i) => (
        <span className="chat-att chat-att--pending" key={`${a.name}-${i}`}>
          <span className="chat-att__name">{a.name}</span>
          <span className="chat-att__meta muted">{a.size ?? 0} B</span>
        </span>
      ))}
    </div>
  );
}

interface LiveBubbleProps {
  live: NormalizedTurn;
  selectedAgent: ChatAgent;
  streaming: boolean;
  resolvedHitls: Record<string, string>;
  onResolve: (id: string, status: string) => void;
  onOpenRun: (runId: string) => void;
  speech: Speech;
}

export function LiveBubble({
  live,
  selectedAgent,
  streaming,
  resolvedHitls,
  onResolve,
  onOpenRun,
  speech,
}: LiveBubbleProps): JSX.Element {
  return (
    <div className="chat-msg chat-msg--assistant">
      <div className="chat-msg__head">
        <AgentAvatar agent={selectedAgent} size={22} status={false} />
        <span className="chat-msg__role">{selectedAgent.name}</span>
        <span className="chat-msg__time">live</span>
      </div>
      <div className="chat-msg__bubble">
        <TurnExtras turn={live} resolvedHitls={resolvedHitls} onResolve={onResolve} onOpenRun={onOpenRun} />
        {live.text ? (
          <MarkdownText value={live.text} />
        ) : (
          streaming && !live.reasoning && (
            <div className="thinking-indicator" style={{ "--agent-color": selectedAgent.color } as React.CSSProperties}>
              <AgentAvatar agent={selectedAgent} size={22} status={false} />
              <span className="thinking-dot" style={{ animationDelay: "0s" }} />
              <span className="thinking-dot" style={{ animationDelay: "0.14s" }} />
              <span className="thinking-dot" style={{ animationDelay: "0.28s" }} />
              <em>thinking</em>
            </div>
          )
        )}
        {live.text && (
          <div className="chat-msg__meta">
            <CopyButton text={live.text} label="Copy" className="chat-msg__action" iconOnly />
            {!streaming && <SpeakButton speech={speech} msgKey="auto:live" text={live.text} iconOnly />}
          </div>
        )}
      </div>
    </div>
  );
}

interface StatusOverlaysProps {
  stopped: boolean;
  streamError: string | null;
  liveRunId: string | null;
  showJump: boolean;
  onWatchAgain: () => void;
  onReconnect: () => void;
  onJumpToLatest: () => void;
}

export function StatusOverlays({
  stopped,
  streamError,
  liveRunId,
  showJump,
  onWatchAgain,
  onReconnect,
  onJumpToLatest,
}: StatusOverlaysProps): JSX.Element {
  return (
    <>
      {stopped && (
        <div className="chat__stopped">
          <span>Stopped watching. The agent may still be finishing on the server.</span>
          <button className="btn" onClick={() => void onWatchAgain()}>
            Watch again
          </button>
          <button className="btn btn--ghost" onClick={() => void onReconnect()}>
            Refresh transcript
          </button>
        </div>
      )}

      {streamError && (
        <div className="chat__reconnect">
          <span className="error">Stream interrupted: {streamError}</span>
          {liveRunId && <button className="btn" onClick={() => void onWatchAgain()}>Reconnect live</button>}
          <button className="btn" onClick={() => void onReconnect()}>
            Refresh transcript
          </button>
        </div>
      )}

      {showJump && (
        <button
          className="chat__jump"
          type="button"
          onClick={onJumpToLatest}
          aria-label="Jump to bottom"
          style={{ left: "50%", transform: "translateX(-50%)", bottom: 12 }}
        >
          <Icon name="chevDown" size={18} />
        </button>
      )}
    </>
  );
}

export type {
  MessageListProps,
  PendingBubbleProps,
  LiveBubbleProps,
  StatusOverlaysProps,
};
