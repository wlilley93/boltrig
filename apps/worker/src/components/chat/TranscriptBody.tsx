import { Fragment } from "react";
import type { ConversationModelContext } from "@wlilley93/boltrig-web-sdk";

import { CompactionLine } from "./CompactionLine";

/**
 * The durable messages, with the compaction boundary placed among them.
 *
 * WHY THIS IS ITS OWN COMPONENT. Placing the boundary means knowing the order
 * of the rendered messages, and nothing else in ChatView needs that. Keeping it
 * here means the marker's two placement rules -- inline when the boundary
 * message is on screen, at the end when it is not -- live next to the loop they
 * depend on rather than being split across a large component.
 */
export function TranscriptBody<T extends { id: string; run_id?: string | null }>({
  messages,
  modelContext,
  boundaryId,
  renderMessage,
}: {
  messages: readonly T[];
  modelContext: ConversationModelContext | null;
  /** The rendered message the boundary follows, or null -- see ChatView. */
  boundaryId: string | null;
  renderMessage: (message: T) => JSX.Element;
}) {
  const line = modelContext?.compacted
    ? (
      <CompactionLine
        coveredCount={modelContext.covered_count}
        recentExactCount={modelContext.recent_exact_count}
        summary={modelContext.summary}
      />
    )
    : null;

  return (
    <>
      {messages.map((message) => (
        <Fragment key={message.id}>
          {renderMessage(message)}
          {/* The boundary is a POSITION, so the marker belongs in the flow
              rather than after it: above this line the model receives a
              summary, below it the turns arrive verbatim. */}
          {boundaryId === message.id ? line : null}
        </Fragment>
      ))}
      {/* The boundary message is not always in view -- a regeneration can
          supersede it, and an older conversation may not carry it at all.
          Inline is the right place when it exists; dropping the disclosure
          when it does not would be worse than putting it last. */}
      {line && boundaryId === null ? line : null}
    </>
  );
}
