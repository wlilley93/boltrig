import { useEffect, useRef, useState } from "react";
import type { HitlEntry } from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";

/** Affirmative decisions get the accent button; everything else stays quiet. */
function isAffirmative(choice: string): boolean {
  return /^(approve|allow|yes|confirm)$/i.test(choice);
}

function titleCase(choice: string): string {
  return choice.charAt(0).toUpperCase() + choice.slice(1);
}

interface InspectFacts {
  inputs?: unknown;
  state?: string;
  error?: string;
}

/** The replayed card in a settled transcript: the request belongs to a turn
 * that already ended, so it is deliberately not answerable from here. */
export function SettledApproval({ entry, tech }: { entry: HitlEntry; tech: boolean }) {
  return (
    <div className="inline-approval" data-phase="replay">
      <div className="inline-approval-head">
        <span aria-hidden />
        <strong>{entry.question}</strong>
        {tech && entry.verb && <span className="verb-chip">{entry.verb}</span>}
      </div>
      <div className="inline-approval-body">
        <p className="muted small">
          This approval was part of a completed turn and can no longer be
          answered here.
        </p>
      </div>
    </div>
  );
}

interface InlineApprovalProps {
  entry: HitlEntry;
  /** Developer detail: show the monospace verb chip. */
  tech: boolean;
  /** The live turn has already ended: point at the Inbox instead of offering
      buttons against a request whose run has moved on. */
  disabled?: boolean;
}

/** The inline approval card: Approve / the other real options, straight from
 * the stream's HITL request, answered through the same governed
 * client.respondHitl the Inbox uses. The card settles optimistically on click
 * and reverts with the kernel's reason if the response is not accepted -
 * a request already settled elsewhere can never be double-answered into
 * success. "See exactly what runs" pulls the request's recorded inputs and
 * current approval state; nothing is paraphrased. */
export function InlineApproval({ entry, tech, disabled = false }: InlineApprovalProps) {
  const [phase, setPhase] = useState<"open" | "sending" | "settled" | "failed">("open");
  const [decision, setDecision] = useState("");
  const [note, setNote] = useState("");
  const [inspectOpen, setInspectOpen] = useState(false);
  const [inspect, setInspect] = useState<InspectFacts | null>(null);
  const inFlight = useRef(false);
  // The decision buttons unmount the moment a choice is made, which would drop
  // focus to <body> and send the next Tab to the top of the document. The card
  // body survives every phase, so focus lands there and reading continues from
  // the place the user was.
  const bodyRef = useRef<HTMLDivElement>(null);
  const wasOpen = useRef(true);
  useEffect(() => {
    if (phase === "open") {
      wasOpen.current = true;
      return;
    }
    if (!wasOpen.current) return;
    wasOpen.current = false;
    bodyRef.current?.focus();
  }, [phase]);

  const provided = entry.options.filter(Boolean);
  const choices = provided.length > 0
    ? provided
    : entry.kind === "approval" ? ["approve", "deny"] : [];

  async function respond(choice: string) {
    if (inFlight.current || phase === "sending" || phase === "settled") return;
    inFlight.current = true;
    setDecision(choice);
    // Optimistic settle: the card flips immediately and reverts on rejection.
    setPhase("sending");
    setNote("");
    try {
      const result = await client.respondHitl(entry.hitlRequestId, choice);
      if (result.status === "ok" || result.status === "answered") {
        setPhase("settled");
        setNote(`Your decision "${choice}" was recorded. The run continues.`);
      } else {
        setPhase("failed");
        setNote(result.reason ?? `The response was not accepted (${result.status}).`);
      }
    } catch {
      setPhase("failed");
      setNote("The response could not be sent. It is safe to retry.");
    } finally {
      inFlight.current = false;
    }
  }

  async function toggleInspect() {
    const opening = !inspectOpen;
    setInspectOpen(opening);
    if (!opening || inspect) return;
    try {
      const [list, state] = await Promise.allSettled([
        client.hitl(),
        client.invokeApprovalState(entry.hitlRequestId),
      ]);
      const request = list.status === "fulfilled"
        ? list.value.requests.find((item) => item.id === entry.hitlRequestId)
        : undefined;
      setInspect({
        inputs: request?.inputs,
        state: state.status === "fulfilled" ? state.value.status : undefined,
        error: !request && state.status !== "fulfilled"
          ? "The request details could not be loaded. It is safe to retry."
          : undefined,
      });
    } catch {
      setInspect({ error: "The request details could not be loaded. It is safe to retry." });
    }
  }

  return (
    <div className="inline-approval" data-phase={phase}>
      <div className="inline-approval-head">
        <span aria-hidden />
        <strong>{entry.question}</strong>
        {tech && entry.verb && <span className="verb-chip">{entry.verb}</span>}
      </div>
      <div className="inline-approval-body" ref={bodyRef} tabIndex={-1}>
        {disabled ? (
          <p className="muted small">
            This turn has settled. If the request is still pending it is
            waiting in the <a href="#/inbox">Inbox</a>.
          </p>
        ) : phase === "settled" || phase === "sending" ? (
          <p role="status">
            {phase === "sending" ? `Sending "${decision}"…` : note}
          </p>
        ) : (
          <div className="inline-approval-actions">
            {choices.map((choice) => (
              <button
                className={isAffirmative(choice)
                  ? "inline-approval-affirm"
                  : "inline-approval-other"}
                key={choice}
                onClick={() => void respond(choice)}
                type="button"
              >
                {titleCase(choice)}
              </button>
            ))}
            {choices.length === 0 && (
              <p className="muted small">
                This request needs a written response. Answer it in the{" "}
                <a href="#/inbox">Inbox</a>.
              </p>
            )}
            <button
              className="inline-approval-inspect"
              onClick={() => void toggleInspect()}
              type="button"
            >
              {inspectOpen ? "Hide the details" : "See exactly what runs"}
            </button>
          </div>
        )}
        {phase === "failed" && note && <p className="notice" role="alert">{note}</p>}
        {inspectOpen && !disabled && phase !== "settled" && (
          <div className="inline-approval-facts">
            {inspect === null && <p className="muted small">Loading the request…</p>}
            {inspect?.error && <p className="notice" role="alert">{inspect.error}</p>}
            {inspect?.state && (
              <p className="muted small">Approval state: {inspect.state}</p>
            )}
            {inspect && inspect.inputs !== undefined && inspect.inputs !== null && (
              <details className="hitl-literal" open>
                <summary>Inputs</summary>
                <pre>{literal(inspect.inputs)}</pre>
              </details>
            )}
            {inspect && !inspect.error && inspect.inputs == null && (
              <p className="muted small">
                The pending request carries no recorded inputs to show.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function literal(value: unknown): string {
  const rendered = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (rendered || String(value)).slice(0, 8_000);
}
