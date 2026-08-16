import type {
  ChatMessage,
  StepEntry,
} from "@wlilley93/boltrig-web-sdk";
import { useState, type DragEvent, type KeyboardEvent } from "react";

import { CHAT_QUEUE_DRAG_TYPE } from "./ComposerAttachments";

const PREVIEWABLE_IMAGES = new Set([
  "image/gif",
  "image/jpeg",
  "image/png",
  "image/webp",
]);

function queuedLabel(message: ChatMessage): string {
  const content = message.content.trim();
  if (content) return content;
  const attachments = message.attachments ?? [];
  if (attachments.length === 0) return "Queued instruction";
  const images = attachments.filter((item) => item.media_type.toLowerCase().startsWith("image/"));
  if (images.length === attachments.length) {
    return `${images.length} image${images.length === 1 ? "" : "s"}`;
  }
  return `${attachments.length} attachment${attachments.length === 1 ? "" : "s"}`;
}

function QueuedPreview({ message }: { message: ChatMessage }) {
  const attachments = message.attachments ?? [];
  if (attachments.length === 0) return null;
  const image = attachments.find((item) => PREVIEWABLE_IMAGES.has(item.media_type.toLowerCase()));
  return (
    <span aria-hidden className="queued-message-preview">
      {image ? (
        <img alt="" src={`data:${image.media_type};base64,${image.data}`} />
      ) : (
        <svg fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24">
          <path d="M6 2h8l4 4v16H6z" /><path d="M14 2v5h5M9 13h6M9 17h5" />
        </svg>
      )}
    </span>
  );
}

type StepTone = "done" | "running" | "waiting" | "failed";

function stepTone(status: StepEntry["status"]): StepTone {
  if (status === "ok" || status === "skipped") return "done";
  if (status === "running") return "running";
  if (status === "paused") return "waiting";
  return "failed";
}

function stepState(status: StepEntry["status"]): string {
  switch (status) {
    case "ok": return "Complete";
    case "skipped": return "Skipped";
    case "running": return "In progress";
    case "paused": return "Paused";
    case "failed": return "Failed";
    case "error": return "Error";
  }
}

function currentStepIndex(steps: StepEntry[]): number {
  const active = steps.findIndex((step) => step.status === "running");
  if (active >= 0) return active;
  const blocked = steps.findIndex((step) => step.status === "paused");
  if (blocked >= 0) return blocked;
  const incomplete = steps.findIndex((step) => step.status === "failed" || step.status === "error");
  if (incomplete >= 0) return incomplete;
  return Math.max(0, steps.length - 1);
}

/** Compact progress for the workflow steps the kernel actually published. */
export function RunProgress({ steps }: { steps: StepEntry[] }) {
  if (steps.length === 0) return null;
  const current = currentStepIndex(steps);
  const settled = steps.every((step) => step.status === "ok" || step.status === "skipped");
  const label = settled
    ? `${steps.length} / ${steps.length} finished`
    : `Step ${current + 1} / ${steps.length}`;
  const tone = settled ? "done" : stepTone(steps[current].status);
  const state = settled ? "Finished" : stepState(steps[current].status);

  return (
    <details className="run-progress">
      <summary aria-label={`${label}. ${state}. Run steps`} className="run-progress-pill">
        <span aria-hidden className="run-progress-ring" data-tone={tone} />
        <span>{label}</span>
      </summary>
      <ol aria-label="Run steps" className="run-progress-list">
        {steps.map((step) => {
          const itemState = stepState(step.status);
          return (
            <li data-tone={stepTone(step.status)} key={step.stepId}>
              <span aria-hidden className="run-progress-step-mark" />
              <span className="run-progress-step-copy">{step.action}</span>
              <span className="run-progress-sr">{itemState}</span>
            </li>
          );
        })}
      </ol>
    </details>
  );
}

function moved(order: string[], id: string, nextIndex: number): string[] {
  const currentIndex = order.indexOf(id);
  if (currentIndex < 0 || currentIndex === nextIndex) return order;
  const next = [...order];
  next.splice(currentIndex, 1);
  next.splice(nextIndex, 0, id);
  return next;
}

function useQueueReorder(
  messages: ChatMessage[],
  disabled: boolean,
  onReorder?: (expectedMessageIds: string[], messageIds: string[]) => void | Promise<void>,
) {
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [dragOrder, setDragOrder] = useState<string[] | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const messageById = new Map(messages.map((message) => [message.id, message]));
  const sourceOrder = messages.map((message) => message.id);
  const renderedIds = dragOrder
    ? [
        ...dragOrder.filter((id) => messageById.has(id)),
        ...sourceOrder.filter((id) => !dragOrder.includes(id)),
      ]
    : sourceOrder;
  const renderedMessages = renderedIds.flatMap((id) => {
    const message = messageById.get(id);
    return message ? [message] : [];
  });
  function commit(id: string, next: string[]) {
    if (!onReorder || next.join("\0") === sourceOrder.join("\0")) return;
    const message = messageById.get(id);
    if (!message) return;
    setAnnouncement(
      `${queuedLabel(message)} moved to position ${next.indexOf(id) + 1} of ${next.length}.`,
    );
    void onReorder(sourceOrder, next);
  }
  function keyMove(event: KeyboardEvent, message: ChatMessage) {
    const current = sourceOrder.indexOf(message.id);
    let nextIndex = current;
    if (event.key === "ArrowUp") nextIndex = Math.max(0, current - 1);
    else if (event.key === "ArrowDown") nextIndex = Math.min(sourceOrder.length - 1, current + 1);
    else if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = sourceOrder.length - 1;
    else return;
    event.preventDefault();
    commit(message.id, moved(sourceOrder, message.id, nextIndex));
  }
  return {
    announcement, draggingId, renderedMessages,
    canReorder: Boolean(onReorder && messages.length > 1),
    dragEnd() { setDraggingId(null); setDragOrder(null); },
    dragOver(event: DragEvent, message: ChatMessage) {
      if (!draggingId || disabled) return;
      event.preventDefault();
      const order = dragOrder ?? sourceOrder;
      setDragOrder(moved(order, draggingId, order.indexOf(message.id)));
    },
    dragStart(event: DragEvent, message: ChatMessage) {
      if (disabled) { event.preventDefault(); return; }
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData(CHAT_QUEUE_DRAG_TYPE, message.id);
      event.dataTransfer.setData("text/plain", message.id);
      setDraggingId(message.id); setDragOrder(sourceOrder);
    },
    drop(event: DragEvent) {
      if (!draggingId || disabled) return;
      event.preventDefault();
      commit(draggingId, dragOrder ?? sourceOrder);
      setDraggingId(null); setDragOrder(null);
    },
    keyMove,
  };
}

function QueuedMessageRow({
  disabled, message, model, onSteer,
}: {
  disabled: boolean;
  message: ChatMessage;
  model: ReturnType<typeof useQueueReorder>;
  onSteer(message: ChatMessage): void;
}) {
  const label = queuedLabel(message);
  return (
    <article
      className="queued-message"
      data-has-attachment={(message.attachments?.length ?? 0) > 0 ? "true" : undefined}
      data-message-id={message.id}
      data-reordering={model.draggingId === message.id ? "true" : undefined}
      onDragOver={(event) => model.dragOver(event, message)}
      onDrop={model.drop}
    >
      {model.canReorder && <button
        aria-keyshortcuts="ArrowUp ArrowDown Home End"
        aria-label={`Reorder queued message: ${label}`}
        className="queued-message-handle"
        data-reorder-id={message.id}
        disabled={disabled}
        draggable={!disabled}
        onDragEnd={model.dragEnd}
        onDragStart={(event) => model.dragStart(event, message)}
        onKeyDown={(event) => model.keyMove(event, message)}
        title="Drag to reorder. Use arrow keys when focused."
        type="button"
      >
        <svg aria-hidden fill="currentColor" viewBox="0 0 12 18">
          <circle cx="3" cy="4" r="1" /><circle cx="9" cy="4" r="1" />
          <circle cx="3" cy="9" r="1" /><circle cx="9" cy="9" r="1" />
          <circle cx="3" cy="14" r="1" /><circle cx="9" cy="14" r="1" />
        </svg>
      </button>}
      <span aria-hidden className="queued-message-glyph">↳</span>
      <QueuedPreview message={message} />
      <div className="queued-message-copy"><p title={label}>{label}</p></div>
      <button
        aria-label={`Steer queued message: ${label}`}
        className="queued-message-steer"
        onClick={() => onSteer(message)}
        title="Load this queued instruction into the composer"
        type="button"
      >↳ Steer</button>
    </article>
  );
}

export function QueuedMessages({
  disabled = false, messages, onReorder, onSteer,
}: {
  disabled?: boolean;
  messages: ChatMessage[];
  onReorder?(expectedMessageIds: string[], messageIds: string[]): void | Promise<void>;
  onSteer(message: ChatMessage): void;
}) {
  const model = useQueueReorder(messages, disabled, onReorder);

  return (
    <section aria-label="Queued messages" className="queued-messages">
      <span aria-live="polite" className="run-progress-sr">{model.announcement}</span>
      {model.renderedMessages.map((message) => (
        <QueuedMessageRow
          disabled={disabled}
          key={message.id}
          message={message}
          model={model}
          onSteer={onSteer}
        />
      ))}
    </section>
  );
}

export function ComposerRunStatus({
  disabled = false,
  messages,
  onReorder,
  onSteer,
  steps,
}: {
  disabled?: boolean;
  messages: ChatMessage[];
  onReorder?(expectedMessageIds: string[], messageIds: string[]): void | Promise<void>;
  onSteer(message: ChatMessage): void;
  steps: StepEntry[];
}) {
  if (steps.length === 0 && messages.length === 0) return null;
  return (
    <>
      <RunProgress steps={steps} />
      {messages.length > 0 && (
        <QueuedMessages
          disabled={disabled}
          messages={messages}
          onReorder={onReorder}
          onSteer={onSteer}
        />
      )}
    </>
  );
}
