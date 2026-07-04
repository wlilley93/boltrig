/** PendingHumanCard (N15, P30 + AMENDMENTS item 1). */
// The kernel's HITL gate fires BEFORE execution (dispatch.py:212-232): approval
// does not apply the change. This card polls the pending list and, when the id
// leaves it, re-invokes the SAME verb + params with approval_id (consumed
// single-use and verb-bound, hitl.py:131-154) and renders THAT result union.
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/api/client";
import type { InvokeResult } from "@/api/types";
import { useSlideActive } from "@/deck/context";
import { navigate } from "@/router";
import { apiReason, CodeBlock } from "@/panels/shared";
import { AUDIT_STATUS, Hint, StatusBadge } from "@/panels/ux";
import { copyText } from "@/panels/uxFlow/copyText";
import { Disclosure } from "@/panels/uxFlow/disclosure";

const HITL_POLL_MS = 8000;
// Fresh key per re-invoke (amendment 1): the apply is a new execution, and the
// idempotency check sits AFTER the gate (dispatch.py steps 4 then 6).
function freshIdempotencyKey(): string {
  return `phc-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
type PendingPhase =
  | { phase: "waiting" }
  | { phase: "applying" }
  | { phase: "applied"; result: Extract<InvokeResult, { status: "ok" | "degraded" }> }
  | { phase: "denied"; reason: string }
  | { phase: "failed"; reason: string; retryable: boolean }
  | { phase: "not_approved"; freshHitlId: string }
  | { phase: "approved_unapplied" };

function pendingHeadline(phase: PendingPhase["phase"]): string {
  switch (phase) {
    case "waiting":
    case "applying":
      return "Paused for approval";
    case "applied":
      return "Approved - applied";
    case "denied":
      return "Not applied";
    case "failed":
      return "Applying failed";
    case "not_approved":
      return "The request was not approved.";
    case "approved_unapplied":
      return "Approved - not yet applied";
  }
}
type Accent = "ok" | "down" | "amber";

function phaseAccent(phase: PendingPhase["phase"]): Accent {
  if (phase === "applied") return "ok";
  if (phase === "denied" || phase === "not_approved" || phase === "failed") return "down";
  return "amber";
}
function usePendingHumanApply({
  noun,
  verb,
  sentParams,
  hitlRequestId,
  setState,
  onAppliedRef,
  onDeniedRef,
}: {
  noun: string;
  verb: string;
  sentParams: Record<string, unknown> | null;
  hitlRequestId: string;
  setState: React.Dispatch<React.SetStateAction<PendingPhase>>;
  onAppliedRef: React.MutableRefObject<(result: InvokeResult) => void>;
  onDeniedRef: React.MutableRefObject<((reason: string) => void) | undefined>;
}) {
  const invokedRef = useRef(false);
  return useCallback(() => {
    if (sentParams === null) {
      // Amendment 1 + A3: only a re-invoke applies the change; without the
      // params this session cannot perform it (and cannot even distinguish
      // approve from reject - the pending list holds only PENDING rows).
      setState({ phase: "approved_unapplied" });
      return;
    }
    if (invokedRef.current) return;
    invokedRef.current = true;
    setState({ phase: "applying" });
    void (async () => {
      let result: InvokeResult;
      try {
        result = await api.invoke({
          noun,
          verb,
          params: sentParams,
          approval_id: hitlRequestId,
          idempotency_key: freshIdempotencyKey(),
        });
      } catch (err) {
        // transport failure: the gate may not have been reached; retry is offered
        invokedRef.current = false;
        setState({ phase: "failed", reason: apiReason(err), retryable: true });
        return;
      }
      switch (result.status) {
        case "ok":
        case "degraded":
          setState({ phase: "applied", result });
          onAppliedRef.current(result);
          break;
        case "denied":
          setState({ phase: "denied", reason: result.reason });
          onDeniedRef.current?.(result.reason);
          break;
        case "error":
          // the gate consumed the approval before execution failed; a retry
          // would only raise a fresh approval, so none is offered
          setState({ phase: "failed", reason: result.reason, retryable: false });
          break;
        case "pending_human":
          // Disappearance from the pending list is ambiguous between approve
          // and reject; this re-invoke resolves it. consume_if_approved fails
          // closed on a rejected, expired or already-spent approval
          // (hitl.py:131-154) and dispatch then raises a FRESH pause, so a
          // second pending_human here means the request was not approved.
          setState({ phase: "not_approved", freshHitlId: result.hitl_request_id });
          break;
      }
    })();
  }, [noun, verb, sentParams, hitlRequestId, setState]);
}
function usePendingHumanState({
  hitlRequestId,
  verb,
  noun,
  sentParams,
  onApplied,
  onDenied,
}: {
  hitlRequestId: string;
  verb: string;
  noun: string;
  sentParams: Record<string, unknown> | null;
  onApplied: (result: InvokeResult) => void;
  onDenied?: (reason: string) => void;
}) {
  const slideActive = useSlideActive();
  const [state, setState] = useState<PendingPhase>({ phase: "waiting" });
  const [pollNote, setPollNote] = useState<string | null>(null);
  // callbacks live in refs so a per-render parent lambda never restarts the poll
  const onAppliedRef = useRef(onApplied);
  const onDeniedRef = useRef(onDenied);
  useEffect(() => {
    onAppliedRef.current = onApplied;
    onDeniedRef.current = onDenied;
  });

  const applyApproved = usePendingHumanApply({
    noun,
    verb,
    sentParams,
    hitlRequestId,
    setState,
    onAppliedRef,
    onDeniedRef,
  });

  // Poll GET /v1/hitl every 8s while waiting; paused when the slide is
  // inactive (the deck quiesce contract). The route returns only PENDING
  // requests (app.py:392-406), so the poll detects resolution, not outcome.
  useEffect(() => {
    if (state.phase !== "waiting" || !slideActive) return;
    let cancelled = false;
    const check = async () => {
      try {
        const res = await api.hitl();
        if (cancelled) return;
        setPollNote(null);
        if (!res.requests.some((r) => r.id === hitlRequestId)) applyApproved();
      } catch (err) {
        if (!cancelled) setPollNote(apiReason(err));
      }
    };
    void check();
    const timer = window.setInterval(() => void check(), HITL_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [state.phase, slideActive, hitlRequestId, applyApproved]);

  return { state, pollNote, applyApproved };
}
function IdCopy({ id }: { id: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="ux-pending__id"
      title={copied ? "Copied" : "Click to copy"}
      onClick={() => {
        void copyText(id).then((ok) => {
          if (!ok) return;
          setCopied(true);
          window.setTimeout(() => setCopied(false), 2000);
        });
      }}
    >
      <code>{id}</code>
      <span className="ux-pending__copy">{copied ? "copied" : "copy"}</span>
    </button>
  );
}
function PendingHumanHeader({ phase }: { phase: PendingPhase["phase"] }) {
  return (
    <header className="ux-pending__head">
      <strong className="ux-pending__headline">{pendingHeadline(phase)}</strong>
      {(phase === "waiting" || phase === "applying") && (
        <StatusBadge value="pending_human" glossary={AUDIT_STATUS} />
      )}
    </header>
  );
}

function PendingHumanWaitingSentence() {
  return (
    <p className="ux-pending__sentence">
      A person needs to approve this before it takes effect.
    </p>
  );
}

function PendingHumanWaitingHint({ pollNote }: { pollNote: string | null }) {
  return (
    <p className="ux-hint">
      Waiting for a decision. This card checks every 8 seconds.
      {pollNote ? ` Last check failed: ${pollNote}` : ""}
    </p>
  );
}

function PendingHumanApplied({
  result,
}: {
  result: Extract<InvokeResult, { status: "ok" | "degraded" }>;
}) {
  return (
    <>
      <p className="ux-pending__ok">
        {result.status === "degraded"
          ? "Applied, but a system was unhealthy; the result may be partial."
          : "Approved and applied."}
      </p>
      <Disclosure summary="Result">
        <CodeBlock value={result.output} />
      </Disclosure>
    </>
  );
}

function PendingHumanFailed({
  reason,
  retryable,
  onRetry,
}: {
  reason: string;
  retryable: boolean;
  onRetry: () => void;
}) {
  return (
    <>
      <p className="ux-pending__down">{reason}</p>
      {retryable ? (
        <span>
          <button type="button" className="btn btn--sm" onClick={onRetry}>
            Try again
          </button>
        </span>
      ) : (
        <Hint>
          Running this again needs a fresh approval - start again from the form.
        </Hint>
      )}
    </>
  );
}

function PendingHumanNotApproved({ freshHitlId }: { freshHitlId: string }) {
  return (
    <>
      <p className="ux-pending__down">
        The approval did not clear the kernel gate - it was rejected, expired, or already used.
      </p>
      <p className="ux-hint">
        The re-invoke raised a new approval request: <code>{freshHitlId}</code>
      </p>
    </>
  );
}

function PendingHumanApprovedUnapplied() {
  return (
    <>
      <span>
        <button type="button" className="btn" disabled>
          Apply
        </button>
      </span>
      <Hint>
        This session no longer holds the parameters that were sent, so the change
        cannot be applied from here. Cross-session apply lands with backend
        dependency A3 (structured HITL context). Re-run the change from its form,
        or ask in chat.
      </Hint>
    </>
  );
}

function PendingHumanBottom({
  state,
  pollNote,
  onRetry,
}: {
  state: PendingPhase;
  pollNote: string | null;
  onRetry: () => void;
}) {
  switch (state.phase) {
    case "waiting":
      return <PendingHumanWaitingHint pollNote={pollNote} />;
    case "applying":
      return <p className="ux-pending__status">Approved - applying...</p>;
    case "applied":
      return <PendingHumanApplied result={state.result} />;
    case "denied":
      return <p className="ux-pending__down">Denied: {state.reason}</p>;
    case "failed":
      return (
        <PendingHumanFailed
          reason={state.reason}
          retryable={state.retryable}
          onRetry={onRetry}
        />
      );
    case "not_approved":
      return <PendingHumanNotApproved freshHitlId={state.freshHitlId} />;
    case "approved_unapplied":
      return <PendingHumanApprovedUnapplied />;
  }
}
export function PendingHumanCard({
  hitlRequestId,
  verb,
  noun,
  sentParams,
  onApplied,
  onDenied,
}: {
  hitlRequestId: string;
  verb: string; // the full verb id, e.g. control.workflow.upsert
  noun: string;
  // The exact params of the paused invoke. null = this session never held
  // them (cross-session); applying then needs backend dependency A3.
  sentParams: Record<string, unknown> | null;
  onApplied: (result: InvokeResult) => void;
  onDenied?: (reason: string) => void;
}) {
  const { state, pollNote, applyApproved } = usePendingHumanState({
    hitlRequestId,
    verb,
    noun,
    sentParams,
    onApplied,
    onDenied,
  });

  return (
    <article className={`ux-pending ux-pending--${phaseAccent(state.phase)}`} role="status">
      <PendingHumanHeader phase={state.phase} />
      {state.phase === "waiting" && <PendingHumanWaitingSentence />}
      <p className="ux-pending__verb">
        Requested: <code>{verb}</code>
      </p>
      {sentParams !== null && (
        <Disclosure summary="Sent parameters">
          <CodeBlock value={sentParams} />
        </Disclosure>
      )}
      <div className="ux-pending__idrow">
        <span className="ux-pending__idlabel">Request</span>
        <IdCopy id={hitlRequestId} />
      </div>
      <PendingHumanBottom state={state} pollNote={pollNote} onRetry={applyApproved} />
      <footer className="ux-pending__foot">
        <button
          type="button"
          className="btn btn--sm btn--ghost"
          onClick={() => navigate("/approvals")}
        >
          Open in Approvals
        </button>
      </footer>
    </article>
  );
}
