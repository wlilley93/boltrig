import { Fragment, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  normalizeEvents,
  type ChatEvent,
  type NormalizedTurn,
} from "@wlilley93/boltrig-web-sdk";

import { WorkDisclosure } from "./WorkDisclosure";

interface OrderedWorkTranscriptProps {
  content: string;
  events: ChatEvent[];
  turn: NormalizedTurn;
  settled?: boolean;
  startedAt?: number | null;
  durationSeconds?: number | null;
  emptyText?: string;
}

type PendingPart =
  | { kind: "text"; key: string; content: string }
  | { kind: "work"; key: string; events: ChatEvent[] };

type OrderedPart =
  | { kind: "text"; key: string; content: string }
  | { kind: "work"; key: string; turn: NormalizedTurn };

/**
 * Split an assistant response only when the durable prose is an exact replay of
 * its text deltas. Tool results remain attached to the receipt opened by their
 * call id, so a settled status does not become a second, context-free tool row
 * when it arrives after another prose delta.
 */
function orderedParts(content: string, events: ChatEvent[]): OrderedPart[] | null {
  const reconstructed = events
    .filter((event) => event.type === "text_delta")
    .map((event) => event.delta)
    .join("");
  const hasWork = events.some((event) => (
    event.type === "tool_call" || event.type === "tool_result"
  ));
  if (!hasWork || reconstructed !== content) return null;

  const parts: PendingPart[] = [];
  const groupsByCallId = new Map<string, Extract<PendingPart, { kind: "work" }>>();
  let text = "";
  let textStart = -1;
  let work: Extract<PendingPart, { kind: "work" }> | null = null;

  const flushText = () => {
    if (!text) return;
    parts.push({ kind: "text", key: `text:${textStart}`, content: text });
    text = "";
    textStart = -1;
  };
  const flushWork = () => {
    if (!work) return;
    parts.push(work);
    work = null;
  };
  const currentWork = (index: number) => {
    if (!work) work = { kind: "work", key: `work:${index}`, events: [] };
    return work;
  };

  events.forEach((event, index) => {
    if (event.type === "text_delta") {
      flushWork();
      if (textStart < 0) textStart = index;
      text += event.delta;
      return;
    }
    if (event.type === "tool_call") {
      flushText();
      const group = currentWork(index);
      group.events.push(event);
      if (event.call_id) groupsByCallId.set(event.call_id, group);
      return;
    }
    if (event.type === "hitl" || event.type === "question") {
      // Decision cards remain at the end of the turn, but they still close a
      // tool phase so later calls cannot be summarized as one contiguous job.
      flushWork();
      return;
    }
    if (event.type !== "tool_result") return;

    const callGroup = event.call_id ? groupsByCallId.get(event.call_id) : undefined;
    if (callGroup) {
      // This may update a group already flushed into `parts`; normalization is
      // intentionally deferred until the complete event list has been walked.
      callGroup.events.push(event);
      return;
    }
    flushText();
    currentWork(index).events.push(event);
  });

  flushText();
  flushWork();
  return parts.map((part) => part.kind === "work"
    ? { kind: "work", key: part.key, turn: normalizeEvents(part.events) }
    : part);
}

/**
 * Render compact tool receipts in their truthful prose position. When the raw
 * event copy cannot prove that ordering belongs to `content`, retain the prior
 * safe presentation: canonical content first, then one aggregate receipt.
 */
export function OrderedWorkTranscript({
  content,
  events,
  turn,
  settled = false,
  startedAt,
  durationSeconds,
  emptyText = "",
}: OrderedWorkTranscriptProps) {
  const parts = useMemo(() => orderedParts(content, events), [content, events]);
  if (!parts) {
    return (
      <>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content || emptyText}</ReactMarkdown>
        {events.length > 0 && (
          <WorkDisclosure
            turn={turn}
            settled={settled}
            startedAt={startedAt}
            durationSeconds={durationSeconds}
          />
        )}
      </>
    );
  }

  return (
    <>
      {parts.map((part) => (
        <Fragment key={part.key}>
          {part.kind === "text" ? (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{part.content}</ReactMarkdown>
          ) : (
            <WorkDisclosure
              turn={part.turn}
              settled={settled}
              startedAt={startedAt}
              durationSeconds={durationSeconds}
            />
          )}
        </Fragment>
      ))}
    </>
  );
}
