import { useMemo } from "react";
import {
  normalizeEvents,
  type ChatEvent,
  type ChatMessage,
  type NormalizedTurn,
  type SubagentEntry,
} from "@wlilley93/boltrig-web-sdk";

import { LiveQuestionCard } from "../LiveQuestionCard";
import { useFamiliarBody } from "../StageBody";
import { colossusReplyText } from "./colossusReply";
import { InlineApproval } from "./InlineApproval";
import { OrderedWorkTranscript } from "./OrderedWorkTranscript";
import { PersistedDecision } from "./PersistedDecision";
import { SubagentChips } from "./SubagentChips";
import { DisplayObjectList } from "./display/DisplayObjectList";
import type { DisplayObjectReply } from "./display/DecisionDisplayCards";
import {
  attachmentIdentity,
  downloadAttachment,
  formatBytes,
} from "./attachmentPresentation";

export function Message({
  message,
  agentLabel,
  tech,
  durationSeconds,
  onDecisionResolved,
  onOpenSubagent,
  onDisplayReply,
}: {
  message: ChatMessage;
  agentLabel?: string;
  tech: boolean;
  durationSeconds?: number;
  onDecisionResolved?(): void;
  onOpenSubagent?(agent: SubagentEntry): void;
  onDisplayReply?: DisplayObjectReply;
}) {
  const turn = useMemo(() => normalizeEvents(message.events ?? []), [message.events]);
  // Colossus replies in JSON ({"say", "sign"} — see colossusReply.ts); the
  // chat prints what he SAYS. Every other character's text passes untouched.
  const colossus = useFamiliarBody() === "colossus";
  const content = colossus && message.role === "assistant"
    ? colossusReplyText(message.content)
    : message.content;
  return (
    <article className={`message ${message.role}`}>
      <div className="message-content">
        {agentLabel && <p className="message-agent-label">{agentLabel}</p>}
        {turn.degraded && (
          <p className="notice" role="status">
            This response used a degraded fallback; treat its result as incomplete.
          </p>
        )}
        <OrderedWorkTranscript
          content={content}
          events={message.events ?? []}
          runId={message.run_id ?? undefined}
          turn={turn}
          settled
          durationSeconds={durationSeconds ?? null}
        />
        <DisplayObjectList entries={turn.displayObjects ?? []} settled onReply={onDisplayReply} />
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
          <TurnDecisions turn={turn} settled tech={tech} onDecisionResolved={onDecisionResolved}
            onOpenSubagent={onOpenSubagent} />
        ) : null}
      </div>
    </article>
  );
}

export function LiveTurn({
  events,
  agentLabel,
  turn,
  tech,
  startedAt,
  onOpenSubagent,
  onDisplayReply,
}: {
  events: ChatEvent[];
  agentLabel?: string;
  turn: NormalizedTurn;
  tech: boolean;
  startedAt: number | null;
  onOpenSubagent?(agent: SubagentEntry): void;
  onDisplayReply?: DisplayObjectReply;
}) {
  // Same unwrap as Message, on the STREAMING buffer: his "say" string reads
  // as prose from its first token instead of as an arriving JSON object.
  const liveText = useFamiliarBody() === "colossus"
    ? colossusReplyText(turn.text)
    : turn.text;
  return (
    <article className="message assistant live">
      <div className="message-content">
        {agentLabel && <p className="message-agent-label">{agentLabel}</p>}
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
          content={liveText}
          emptyText="Working…"
          events={events}
          turn={turn}
          startedAt={startedAt}
        />
        <DisplayObjectList entries={turn.displayObjects ?? []} settled={turn.ended} onReply={onDisplayReply} />
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
  onDecisionResolved,
  onOpenSubagent,
}: {
  turn: NormalizedTurn;
  settled?: boolean;
  tech: boolean;
  onDecisionResolved?(): void;
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
          if (settled) return <PersistedDecision
            decision={{ kind: "approval", entry: item.entry }}
            tech={tech}
            onResolved={onDecisionResolved}
            key={item.key}
          />;
          return (
            <InlineApproval
              entry={item.entry}
              tech={tech}
              disabled={turn.ended}
              onResolved={onDecisionResolved}
              key={item.key}
            />
          );
        }
        if (item.kind === "question") {
          if (settled) return <PersistedDecision
            decision={{ kind: "question", entry: item.entry }}
            tech={tech}
            onResolved={onDecisionResolved}
            key={item.key}
          />;
          return <LiveQuestionCard question={item.entry} key={item.key}
            onAnswered={onDecisionResolved} />;
        }
        return null;
      })}
    </>
  );
}
