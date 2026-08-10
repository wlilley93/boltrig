import { useEffect, useRef, useState } from "react";
import type { ChatMessage, HitlEntry, NormalizedTurn } from "@wlilley93/boltrig-web-sdk";

import { FamiliarBadge } from "./familiar/FamiliarBadge";
import "./chat/chat.css";

// The mobile conversation surface.
//
// This is NOT the console at a narrow width. The decided target draws mobile on
// its own palette — iOS system colours, a separator rather than a border, and
// 44px touch targets — so it opts into `.mobile-surface`, where those tokens are
// scoped. Overriding the console tokens inside a media query would have put two
// authorities behind the same variable names, which is the one shape the token
// layer may not take.

function StateWord({ state }: { state: "done" | "waiting" | "running" }) {
  return (
    <span className="m-state" data-tone={state}>
      {state === "done" ? "done" : state === "waiting" ? "waiting" : "running"}
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
}: {
  hitl: HitlEntry;
  onRespond?(id: string, decision: string): Promise<boolean>;
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
          The response was not accepted. It may already be settled; check the Inbox.
        </p>
      )}
    </div>
  );
}

export function MobileChat({
  title,
  subtitle,
  messages,
  turn,
  onBack,
  onSend,
  busy,
  composerValue,
  onComposerChange,
  onRespondHitl,
}: {
  title: string;
  subtitle: string;
  messages: ChatMessage[];
  turn: NormalizedTurn;
  onBack(): void;
  onSend(): void;
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

  const [traceOpen, setTraceOpen] = useState(false);
  const [planOpen, setPlanOpen] = useState(true);

  const lastUser = [...messages].reverse().find((message) => message.role === "user");
  const lastAssistant = [...messages].reverse().find(
    (message) => message.role === "assistant" && !message.superseded_by,
  );
  const steps = turn.steps;
  const doneSteps = steps.filter((step) => step.status === "ok").length;

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

      <div className="m-body">
        {messages.length === 0 && (
          <p className="m-empty">Say what needs doing. It will plan the work, use the tools this
            workspace grants, and stop for you before anything consequential.</p>
        )}

        {lastUser && (
          <div className="m-user-row">
            <div className="m-bubble">{lastUser.content}</div>
          </div>
        )}

        {(turn.tools.length > 0 || turn.subagents.length > 0) && (
          <>
            <button className="m-trace" onClick={() => setTraceOpen((open) => !open)} type="button">
              <svg fill="none" height="18" stroke="currentColor" strokeLinecap="round" strokeWidth="1.9" viewBox="0 0 24 24" width="18">
                <circle cx="11" cy="11" r="7" /><line x1="16.5" x2="21" y1="16.5" y2="21" />
              </svg>
              <span>
                {`Read ${turn.tools.length} ${turn.tools.length === 1 ? "tool" : "tools"}`}
                {turn.subagents.length > 0 ? `, ${turn.subagents.length} working` : ""}
              </span>
              <span className="m-caret" data-open={traceOpen ? "true" : undefined}>›</span>
            </button>
            {traceOpen && (
              <div className="m-card m-trace-list">
                {turn.tools.map((tool, index) => (
                  <div className="m-trace-row" key={tool.callId ?? `${tool.key}-${index}`}>
                    <span className="m-dot" data-tone={tool.status === "ok" ? "done" : tool.status === "pending" ? "running" : "failed"} />
                    <span className="m-trace-label">{tool.verb}</span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        <div className="m-sep" />

        {lastAssistant && <p className="m-para">{lastAssistant.content}</p>}

        {turn.subagents.length > 0 && (
          <div className="m-tree">
            <div className="m-lead">
              <FamiliarBadge state={turn.ended ? "ready" : "working"} label="lead" />
              <span className="m-lead-label">{turn.subagents.length} working</span>
              <span className="m-lead-sub">leading this</span>
            </div>
            <div className="m-fanout">
              {turn.subagents.map((agent) => (
                <div className="m-fan-row" key={agent.key}>
                  <FamiliarBadge
                    state={turn.ended ? "ready" : "working"}
                    label={agent.name ?? agent.task}
                  />
                  <span className="m-fan-label">{agent.name ?? agent.task}</span>
                  <StateWord state={turn.ended ? "done" : "running"} />
                </div>
              ))}
            </div>
          </div>
        )}

        {steps.length > 0 && (
          <div className="m-card">
            <button className="m-plan-head" onClick={() => setPlanOpen((open) => !open)} type="button">
              <span className="m-plan-title">The plan</span>
              <span className="m-plan-progress">{doneSteps} of {steps.length}</span>
              <span className="m-caret" data-open={planOpen ? "true" : undefined}>›</span>
            </button>
            {planOpen && (
              <div className="m-plan-rows">
                {steps.map((step, index) => (
                  <div className="m-plan-row" key={step.stepId}>
                    <span className="m-dot" data-tone={step.status === "ok" ? "done" : step.status === "failed" || step.status === "error" ? "failed" : "running"} />
                    <span className="m-plan-n">{index + 1}</span>
                    <span className="m-plan-label" data-done={step.status === "ok" ? "true" : undefined}>
                      {step.action}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {turn.hitls.length > 0 && (
          <div className="m-card m-pending">
            {turn.hitls.map((hitl) => (
              <MobilePendingRow
                hitl={hitl}
                key={hitl.hitlRequestId}
                onRespond={onRespondHitl}
              />
            ))}
          </div>
        )}
      </div>

      <div className="m-composer">
        <button aria-label="Attach" className="m-round-sm" type="button">
          <svg fill="none" height="21" stroke="currentColor" strokeLinecap="round" strokeWidth="1.9" viewBox="0 0 24 24" width="21">
            <line x1="12" x2="12" y1="5" y2="19" /><line x1="5" x2="19" y1="12" y2="12" />
          </svg>
        </button>
        <input
          aria-label="Follow up"
          className="m-input"
          onChange={(event) => onComposerChange(event.target.value)}
          placeholder="Follow up"
          value={composerValue}
        />
        <button
          aria-label={busy ? "Stop" : "Send"}
          className="m-send"
          onClick={onSend}
          type="button"
        >
          {busy ? (
            <svg fill="currentColor" height="15" viewBox="0 0 24 24" width="15">
              <rect height="12" rx="2.5" width="12" x="6" y="6" />
            </svg>
          ) : (
            <svg fill="none" height="17" stroke="currentColor" strokeLinecap="round" strokeWidth="2.2" viewBox="0 0 24 24">
              <line x1="12" x2="12" y1="19" y2="5" /><polyline points="6 11 12 5 18 11" />
            </svg>
          )}
        </button>
      </div>
    </div>
  );
}
