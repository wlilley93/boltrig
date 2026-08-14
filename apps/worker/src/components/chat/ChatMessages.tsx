import { useMemo } from "react";
import {
  normalizeEvents,
  type ChatEvent,
  type ChatMessage,
  type NormalizedTurn,
  type SubagentEntry,
} from "@wlilley93/boltrig-web-sdk";

import { LiveQuestionCard } from "../LiveQuestionCard";
import { InlineApproval, SettledApproval } from "./InlineApproval";
import { OrderedWorkTranscript } from "./OrderedWorkTranscript";
import { SubagentChips } from "./SubagentChips";
import {
  attachmentIdentity,
  downloadAttachment,
  formatBytes,
} from "./attachmentPresentation";

export function Message({
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
          runId={message.run_id ?? undefined}
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

export function LiveTurn({
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
        {/* The resolved routing receipt is developer detail; the plain console
            already names the selected model in the composer chip. */}
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
export function TurnDecisions({
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
