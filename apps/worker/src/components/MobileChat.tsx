import { useEffect, useId, useRef, useState } from "react";
import {
  normalizeEvents,
  type ChatMessage,
  type HitlEntry,
  type NormalizedTurn,
} from "@wlilley93/boltrig-web-sdk";

import { FamiliarBadge } from "./familiar/FamiliarBadge";
import { LiveQuestionCard } from "./LiveQuestionCard";
import { WorkDisclosure } from "./chat/WorkDisclosure";
import { MobileQueuedMessages } from "./chat/MobileQueuedMessages";
import "./chat/chat.css";
import "./MobileChatParity.css";

// The mobile conversation surface.
//
// This is NOT the console at a narrow width. The decided target draws mobile on
// its own palette — iOS system colours, a separator rather than a border, and
// 44px touch targets — so it opts into `.mobile-surface`, where those tokens are
// scoped. Overriding the console tokens inside a media query would have put two
// authorities behind the same variable names, which is the one shape the token
// layer may not take.

function statusTone(status: string): "done" | "waiting" | "running" | "failed" | undefined {
  const value = status.toLowerCase();
  if (["ok", "done", "completed", "answered"].includes(value)) return "done";
  if (["waiting", "pending", "paused", "degraded"].includes(value)) return "waiting";
  if (["running", "working", "started"].includes(value)) return "running";
  if (["failed", "error", "rejected"].includes(value)) return "failed";
  return undefined;
}

function StateWord({ state }: { state: string }) {
  return (
    <span className="m-state" data-tone={statusTone(state)}>
      {state}
    </span>
  );
}

/** A pending decision with the same inline approve/decline the console chat
 * offers, kept behaviorally consistent: real options from the request, an
 * optimistic settle that reverts if the kernel refuses, and no buttons at all
 * when no responder is wired. */
function MobilePendingRow({
  hitl,
  onRespond,
  settled,
}: {
  hitl: HitlEntry;
  onRespond?(id: string, decision: string): Promise<boolean>;
  settled?: boolean;
}) {
  const [phase, setPhase] = useState<"open" | "sending" | "done" | "failed">("open");
  const [decision, setDecision] = useState("");
  const inFlight = useRef(false);

  const provided = hitl.options.filter(Boolean);
  const choices = provided.length > 0
    ? provided
    : hitl.kind === "approval" ? ["approve", "deny"] : [];

  async function respond(choice: string) {
    if (!onRespond || inFlight.current || phase === "sending" || phase === "done") return;
    inFlight.current = true;
    setDecision(choice);
    setPhase("sending");
    try {
      setPhase(await onRespond(hitl.hitlRequestId, choice) ? "done" : "failed");
    } catch {
      setPhase("failed");
    } finally {
      inFlight.current = false;
    }
  }

  return (
    <div className="m-pending-row">
      <span className="m-dot" data-tone={phase === "done" ? "done" : "waiting"} />
      <span className="m-pending-label">{hitl.question}</span>
      {onRespond && choices.length > 0 && (phase === "open" || phase === "failed") && (
        <div className="m-pending-actions">
          {choices.map((choice) => (
            <button
              className={/^(approve|allow|yes|confirm)$/i.test(choice) ? "m-approve" : "m-defer"}
              key={choice}
              onClick={() => void respond(choice)}
              type="button"
            >
              {choice.charAt(0).toUpperCase() + choice.slice(1)}
            </button>
          ))}
        </div>
      )}
      {phase === "sending" && <p className="m-pending-note" role="status">Sending "{decision}"…</p>}
      {phase === "done" && (
        <p className="m-pending-note" role="status">Your decision "{decision}" was recorded.</p>
      )}
      {phase === "failed" && (
        <p className="m-pending-note" role="alert">
          The response was not accepted. It may already be settled; return to the originating chat.
        </p>
      )}
      {settled && (
        <p className="m-pending-note">This request belongs to a completed turn and is no longer answerable.</p>
      )}
    </div>
  );
}

function MobileDecisions({
  turn,
  answerable,
  onRespondHitl,
}: {
  turn: NormalizedTurn;
  answerable: boolean;
  onRespondHitl?(id: string, decision: string): Promise<boolean>;
}) {
  if (turn.hitls.length === 0 && turn.questions.length === 0) return null;
  return (
    <div className="m-card m-pending">
      {turn.hitls.map((hitl) => (
        <MobilePendingRow
          hitl={hitl}
          key={hitl.hitlRequestId}
          onRespond={answerable ? onRespondHitl : undefined}
          settled={!answerable}
        />
      ))}
      {turn.questions.map((question) => answerable ? (
        <LiveQuestionCard key={question.questionId} question={question} />
      ) : (
        <div className="m-settled-question" key={question.questionId}>
          <strong>Question from this run</strong>
          <p>{question.prompt}</p>
          <p>This question belongs to a completed turn and is no longer answerable.</p>
        </div>
      ))}
    </div>
  );
}

export function MobileChat({
  title,
  subtitle,
  messages,
  turn,
  turnIsLive,
  turnIsAnswerable,
  newState,
  loadingConversation,
  conversationLoadError,
  error,
  continuity,
  retryFollow,
  queuedMessages,
  composerDisabled,
  closed,
  onBack,
  onSend,
  onStop,
  onRetryConversation,
  onReconnect,
  onReorderQueued,
  onSteerQueued,
  queueReordering,
  busy,
  composerValue,
  onComposerChange,
  onRespondHitl,
}: {
  title: string;
  subtitle: string;
  messages: ChatMessage[];
  turn: NormalizedTurn;
  turnIsLive: boolean;
  turnIsAnswerable: boolean;
  newState: boolean;
  loadingConversation: boolean;
  conversationLoadError: string;
  error: string;
  continuity: string;
  retryFollow: boolean;
  queuedMessages: ChatMessage[];
  composerDisabled: boolean;
  closed: boolean;
  onBack(): void;
  onSend(): void;
  onStop(): void;
  onRetryConversation(): void;
  onReconnect(): void;
  onReorderQueued(expectedMessageIds: string[], messageIds: string[]): void | Promise<void>;
  onSteerQueued(message: ChatMessage): void;
  queueReordering: boolean;
  busy: boolean;
  composerValue: string;
  onComposerChange(value: string): void;
  /** Governed approval responder (client.respondHitl behind it); resolves
      true when the kernel accepted the decision. Absent, pending rows stay
      read-only - the surface never draws a button that goes nowhere. */
  onRespondHitl?(id: string, decision: string): Promise<boolean>;
}) {
  // The mobile surface owns the whole screen: the shell's floating menu button
  // would otherwise sit on top of the back control. The flag is on the root so
  // the shell chrome can stand down without this component reaching into it.
  useEffect(() => {
    document.documentElement.dataset.mobileSurface = "chat";
    return () => { delete document.documentElement.dataset.mobileSurface; };
  }, []);

  const [planOpen, setPlanOpen] = useState(true);
  const planId = useId();
  const bodyRef = useRef<HTMLDivElement>(null);
  const followLatestRef = useRef(true);
  const visibleMessages = messages.filter((message) => !message.superseded_by);
  const renderedMessages = visibleMessages.map((message) => ({
    message,
    durableTurn: message.events?.length ? normalizeEvents(message.events) : null,
  }));
  const hasDurableDecisions = renderedMessages.some(({ durableTurn }) => Boolean(
    durableTurn && (durableTurn.hitls.length > 0 || durableTurn.questions.length > 0),
  ));
  const steps = turn.steps;
  const doneSteps = steps.filter((step) => step.status === "ok").length;

  useEffect(() => {
    const body = bodyRef.current;
    if (body && followLatestRef.current) body.scrollTop = body.scrollHeight;
  }, [messages, turn.text, turn.timeline.length, continuity, error, queuedMessages.length]);

  const composerPlaceholder = closed
    ? "This conversation is closed"
    : conversationLoadError
      ? "Conversation unavailable — retry above"
      : loadingConversation
        ? "Loading conversation state…"
        : "Follow up";

  return (
    <div className="mobile-surface">
      <header className="m-head">
        <button aria-label="Back" className="m-round" onClick={onBack} type="button">
          <svg fill="none" height="19" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.4" viewBox="0 0 24 24" width="19">
            <polyline points="15 5 8 12 15 19" />
          </svg>
        </button>
        <div className="m-head-title">
          <span className="m-title">{title}</span>
          {subtitle && <span className="m-sub">{subtitle}</span>}
        </div>
      </header>

      <div
        aria-label="Conversation transcript"
        aria-live="polite"
        className="m-body"
        onScroll={(event) => {
          const body = event.currentTarget;
          followLatestRef.current = body.scrollHeight - body.scrollTop - body.clientHeight < 80;
        }}
        ref={bodyRef}
        role="log"
        tabIndex={0}
      >
        {newState && visibleMessages.length === 0 && !loadingConversation && !conversationLoadError && (
          <p className="m-empty">Say what needs doing. It will plan the work, use the tools this
            workspace grants, and stop for you before anything consequential.</p>
        )}

        {loadingConversation && (
          <p className="m-notice" role="status">Loading conversation…</p>
        )}

        {conversationLoadError && (
          <div className="m-notice" role="alert">
            <p>Could not load this conversation. {conversationLoadError}</p>
            <button className="m-inline-action" onClick={onRetryConversation} type="button">
              Retry conversation
            </button>
          </div>
        )}

        {renderedMessages.map(({ message, durableTurn }) => {
          const role = message.role === "user"
            ? "user"
            : message.role === "assistant" ? "assistant" : "other";
          return (
            <article className={`m-message m-message-${role}`} key={message.id}>
              {role === "other" && <span className="m-message-role">{message.role}</span>}
              <p>{message.content}</p>
              {(message.attachments?.length ?? 0) > 0 && (
                <ul aria-label="Message attachments" className="m-message-attachments">
                  {message.attachments!.map((attachment, index) => (
                    <li key={`${attachment.name}-${index}`}>{attachment.name}</li>
                  ))}
                </ul>
              )}
              {durableTurn && (
                <MobileDecisions turn={durableTurn} answerable={false} />
              )}
            </article>
          );
        })}

        {turnIsLive && (
          <article aria-label="Live response" className="m-message m-message-assistant m-message-live">
            <p>{turn.text || "Working…"}</p>
          </article>
        )}

        <WorkDisclosure runId={turn.runId} turn={turn} />

        {turn.subagents.length > 0 && (
          <details className="m-tree">
            <summary className="m-lead">
              <span className="m-lead-label">
                {turn.subagents.length} {turn.subagents.length === 1 ? "subagent" : "subagents"}
              </span>
            </summary>
            <div className="m-fanout">
              {turn.subagents.map((agent) => {
                const status = agent.status ?? (turnIsAnswerable ? "running" : "status unavailable");
                return (
                  <div className="m-fan-row" key={agent.key}>
                    <FamiliarBadge
                      genotype={agent.familiarGenotype}
                      state={status === "running" ? "working" : "ready"}
                      label={agent.name ?? agent.task}
                    />
                    <span className="m-fan-label">{agent.name ?? agent.task}</span>
                    <StateWord state={status} />
                  </div>
                );
              })}
            </div>
          </details>
        )}

        {steps.length > 0 && (
          <div className="m-card">
            <button
              aria-controls={planId}
              aria-expanded={planOpen}
              className="m-plan-head"
              onClick={() => setPlanOpen((open) => !open)}
              type="button"
            >
              <span className="m-plan-title">The plan</span>
              <span className="m-plan-progress">{doneSteps} of {steps.length}</span>
              <span className="m-caret" data-open={planOpen ? "true" : undefined}>›</span>
            </button>
            {planOpen && (
              <div className="m-plan-rows" id={planId}>
                {steps.map((step, index) => (
                  <div className="m-plan-row" key={step.stepId}>
                    <span className="m-dot" data-tone={statusTone(step.status)} />
                    <span className="m-plan-n">{index + 1}</span>
                    <span className="m-plan-label" data-done={step.status === "ok" ? "true" : undefined}>
                      {step.action}
                    </span>
                    <StateWord state={step.status} />
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {(turnIsLive || !hasDurableDecisions) && (
          <MobileDecisions
            answerable={turnIsAnswerable}
            onRespondHitl={onRespondHitl}
            turn={turn}
          />
        )}

        {continuity && (
          <div className="m-notice" role="status">
            <p>{continuity}</p>
            {retryFollow && (
              <button className="m-inline-action" onClick={onReconnect} type="button">Reconnect</button>
            )}
          </div>
        )}

        {error && <p className="m-notice" role="alert">{error}</p>}

      </div>

      <div className="m-composer-dock">
        <MobileQueuedMessages
          disabled={queueReordering}
          messages={queuedMessages}
          onReorder={onReorderQueued}
          onSteer={onSteerQueued}
        />
        <div className="m-composer">
          <textarea
            aria-label="Follow up"
            className="m-input"
            disabled={composerDisabled}
            onChange={(event) => onComposerChange(event.target.value)}
            placeholder={composerPlaceholder}
            rows={1}
            value={composerValue}
          />
          <button
            aria-label={busy ? "Stop" : "Send"}
            className="m-send"
            disabled={!busy && (composerDisabled || !composerValue.trim())}
            onClick={busy ? onStop : onSend}
            type="button"
          >
            {busy ? (
              <svg fill="currentColor" height="13" viewBox="0 0 24 24" width="13">
                <rect height="12" rx="2.5" width="12" x="6" y="6" />
              </svg>
            ) : (
              <svg fill="none" height="16" stroke="currentColor" strokeLinecap="round" strokeWidth="2.2" viewBox="0 0 24 24">
                <line x1="12" x2="12" y1="19" y2="5" /><polyline points="6 11 12 5 18 11" />
              </svg>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
