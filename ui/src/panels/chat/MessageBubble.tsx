import { useMemo } from "react";

import type { ChatMessage } from "@/api/types";
import type { Speech } from "@/voice";
import { AgentAvatar } from "@/panels/chat/AgentAvatar";
import { AttachmentList } from "@/panels/chat/AttachmentChip";
import { CopyButton } from "@/panels/chat/CopyButton";
import type { ChatAgent } from "@/panels/chat/constants";
import { whenText } from "@/panels/chat/formatting";
import { Icon } from "@/panels/chat/icons";
import { MarkdownText } from "@/panels/chat/markdown";
import { SpeakButton } from "@/panels/chat/SpeakButton";
import { normalizeEvents, type NormalizedTurn, TurnExtras } from "@/panels/chatTurn";

interface MessageBubbleProps {
  message: ChatMessage;
  agent: ChatAgent;
  resolvedHitls: Record<string, string>;
  onResolve: (id: string, status: string) => void;
  canRegenerate: boolean;
  regenerating: boolean;
  onRegenerate: () => void;
  onOpenRun: (runId: string) => void;
  speech: Speech;
}

interface MessageBubbleBodyProps {
  message: ChatMessage;
  agent: ChatAgent;
  turn: NormalizedTurn;
  resolvedHitls: Record<string, string>;
  onResolve: (id: string, status: string) => void;
  canRegenerate: boolean;
  regenerating: boolean;
  onRegenerate: () => void;
  onOpenRun: (runId: string) => void;
  speech: Speech;
}

function MessageBubbleBody({
  message,
  turn,
  resolvedHitls,
  onResolve,
  canRegenerate,
  regenerating,
  onRegenerate,
  onOpenRun,
  speech,
}: MessageBubbleBodyProps): JSX.Element {
  const isAssistant = message.role === "assistant";

  return (
    <>
      {isAssistant && (
        <TurnExtras
          turn={turn}
          resolvedHitls={resolvedHitls}
          onResolve={onResolve}
          onOpenRun={onOpenRun}
        />
      )}
      {message.content && <MarkdownText value={message.content} />}
      <AttachmentList attachments={message.attachments} />
      {!isAssistant && (
        <span className="chat-msg__time chat-msg__time--bubble" title={message.created_at}>
          {whenText(message.created_at)}
        </span>
      )}
      <div className="chat-msg__meta">
        {message.content && (
          <CopyButton text={message.content} label="Copy" className="chat-msg__action" iconOnly />
        )}
        {isAssistant && message.content && (
          <SpeakButton speech={speech} msgKey={message.id} text={message.content} iconOnly />
        )}
        {canRegenerate && (
          <button
            type="button"
            className="chat-msg__action chat-msg__action--icon"
            aria-label="Regenerate"
            disabled={regenerating}
            style={{ width: 26, height: 26 }}
            onClick={onRegenerate}
          >
            <Icon name="refresh" size={16} />
          </button>
        )}
      </div>
    </>
  );
}

export function MessageBubble(props: MessageBubbleProps): JSX.Element {
  const { message, agent, resolvedHitls, onResolve, canRegenerate, regenerating, onRegenerate, onOpenRun, speech } = props;
  const turn = useMemo(() => normalizeEvents(message.events ?? []), [message.events]);
  const isAssistant = message.role === "assistant";
  const superseded = Boolean(message.superseded_by);

  const body = (
    <MessageBubbleBody
      message={message}
      agent={agent}
      turn={turn}
      resolvedHitls={resolvedHitls}
      onResolve={onResolve}
      canRegenerate={canRegenerate}
      regenerating={regenerating}
      onRegenerate={onRegenerate}
      onOpenRun={onOpenRun}
      speech={speech}
    />
  );

  return (
    <div
      className={`chat-msg chat-msg--${isAssistant ? "assistant" : message.role}${
        superseded ? " chat-msg--superseded" : ""
      }`}
    >
      {isAssistant ? (
        <div className="chat-msg__head">
          <AgentAvatar agent={agent} size={22} status={false} />
          <span className="chat-msg__role">{agent.name}</span>
          <span className="chat-msg__time" title={message.created_at}>{whenText(message.created_at)}</span>
        </div>
      ) : null}
      <div className="chat-msg__bubble">
        {superseded ? (
          <details className="chat-msg__superseded">
            <summary className="chat-msg__supersededhead muted">
              Superseded reply (regenerated) - click to view
            </summary>
            {body}
          </details>
        ) : (
          body
        )}
      </div>
    </div>
  );
}

export { type MessageBubbleProps };
