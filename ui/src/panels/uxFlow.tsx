/* Flow primitives (register N10-N16, N18, N19 + GrantList): the save / confirm /
 * pause vocabulary every surface composes. Constraints carried here:
 * - L4: amber (--color-consequence-high) only where the kernel gate is in play
 *   (PendingHumanCard, the governed SaveBar foreshadow, the consequence tone).
 * - P27/P36: arm-confirm swaps in place; disarms on Escape / Cancel / blur-away
 *   / slide navigation; Enter confirms only on the focused confirm button.
 * - AMENDMENTS item 1: approval does not apply the change - PendingHumanCard
 *   re-invokes the same verb + params with approval_id and renders THAT result.
 * - Semantic --color-* tokens only (see the ux- append in styles.css).
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api } from "@/api/client";
import type { InvokeResult } from "@/api/types";
import { useSlideActive } from "@/deck/context";
import { navigate } from "@/router";
import { apiReason, CodeBlock } from "@/panels/shared";
import { AUDIT_STATUS, Hint, StatusBadge } from "@/panels/ux";
import { copyText } from "@/panels/uxFlow/copyText";

import { ArmConfirm, useArmConfirm } from "@/panels/uxFlow/armConfirm";
export type { ArmTone, UseArmConfirm } from "@/panels/uxFlow/armConfirm";
export { ArmConfirm, useArmConfirm };

export { SaveBar } from "@/panels/uxFlow/saveBar";

import { Disclosure } from "@/panels/uxFlow/disclosure";
export { Disclosure };

export { Skeleton } from "@/panels/uxFlow/skeleton";

export { CoachMark } from "@/panels/uxFlow/coachMark";

export { GrantList } from "@/panels/uxFlow/grantList";

// --- PendingHumanCard (N15, P30 + AMENDMENTS item 1) -------------------------
// The kernel's HITL gate fires BEFORE execution (dispatch.py:212-232): approval
// does not apply the change. This card polls the pending list and, when the id
// leaves it, re-invokes the SAME verb + params with approval_id (consumed
// single-use and verb-bound, hitl.py:131-154) and renders THAT result union.

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
  const slideActive = useSlideActive();
  const [state, setState] = useState<PendingPhase>({ phase: "waiting" });
  const [pollNote, setPollNote] = useState<string | null>(null);
  const invokedRef = useRef(false);
  // callbacks live in refs so a per-render parent lambda never restarts the poll
  const onAppliedRef = useRef(onApplied);
  const onDeniedRef = useRef(onDenied);
  useEffect(() => {
    onAppliedRef.current = onApplied;
    onDeniedRef.current = onDenied;
  });

  const applyApproved = useCallback(() => {
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
  }, [noun, verb, sentParams, hitlRequestId]);

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

  const accent =
    state.phase === "applied"
      ? "ok"
      : state.phase === "denied" ||
          state.phase === "not_approved" ||
          state.phase === "failed"
        ? "down"
        : "amber";

  return (
    <article className={`ux-pending ux-pending--${accent}`} role="status">
      <header className="ux-pending__head">
        <strong className="ux-pending__headline">{pendingHeadline(state.phase)}</strong>
        {(state.phase === "waiting" || state.phase === "applying") && (
          <StatusBadge value="pending_human" glossary={AUDIT_STATUS} />
        )}
      </header>

      {state.phase === "waiting" && (
        <p className="ux-pending__sentence">
          A person needs to approve this before it takes effect.
        </p>
      )}

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

      {state.phase === "waiting" && (
        <p className="ux-hint">
          Waiting for a decision. This card checks every 8 seconds.
          {pollNote ? ` Last check failed: ${pollNote}` : ""}
        </p>
      )}
      {state.phase === "applying" && (
        <p className="ux-pending__status">Approved - applying...</p>
      )}
      {state.phase === "applied" && (
        <>
          <p className="ux-pending__ok">
            {state.result.status === "degraded"
              ? "Applied, but a system was unhealthy; the result may be partial."
              : "Approved and applied."}
          </p>
          <Disclosure summary="Result">
            <CodeBlock value={state.result.output} />
          </Disclosure>
        </>
      )}
      {state.phase === "denied" && (
        <p className="ux-pending__down">Denied: {state.reason}</p>
      )}
      {state.phase === "failed" && (
        <>
          <p className="ux-pending__down">{state.reason}</p>
          {state.retryable ? (
            <span>
              <button type="button" className="btn btn--sm" onClick={applyApproved}>
                Try again
              </button>
            </span>
          ) : (
            <Hint>
              Running this again needs a fresh approval - start again from the
              form.
            </Hint>
          )}
        </>
      )}
      {state.phase === "not_approved" && (
        <>
          <p className="ux-pending__down">
            The approval did not clear the kernel gate - it was rejected,
            expired, or already used.
          </p>
          <p className="ux-hint">
            The re-invoke raised a new approval request:{" "}
            <code>{state.freshHitlId}</code>
          </p>
        </>
      )}
      {state.phase === "approved_unapplied" && (
        <>
          <span>
            <button type="button" className="btn" disabled>
              Apply
            </button>
          </span>
          <Hint>
            This session no longer holds the parameters that were sent, so the
            change cannot be applied from here. Cross-session apply lands with
            backend dependency A3 (structured HITL context). Re-run the change
            from its form, or ask in chat.
          </Hint>
        </>
      )}

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

export { ByChat } from "@/panels/uxFlow/byChat";

// --- SecretOnce (N18, settings spec 1.5/3): show-once secret material -------
// Warn tone, never amber: no kernel governance is in play (L4).

export function SecretOnce({
  secret,
  title,
  body,
  meta,
  onDone,
  copyLabel,
}: {
  secret: string;
  title?: ReactNode;
  body?: ReactNode;
  meta?: ReactNode; // e.g. token name + expiry + a GrantList of its scope
  onDone: () => void;
  copyLabel?: string;
}) {
  const [copiedFlash, setCopiedFlash] = useState(false);
  const [everCopied, setEverCopied] = useState(false);
  const blockRef = useRef<HTMLPreElement>(null);

  // While mounted the secret exists nowhere else; guard accidental unloads.
  useEffect(() => {
    const guard = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, []);

  const selectAll = () => {
    const el = blockRef.current;
    const sel = window.getSelection();
    if (!el || !sel) return;
    const range = document.createRange();
    range.selectNodeContents(el);
    sel.removeAllRanges();
    sel.addRange(range);
  };

  const copy = () => {
    void copyText(secret).then((ok) => {
      if (ok) {
        setEverCopied(true);
        setCopiedFlash(true);
        window.setTimeout(() => setCopiedFlash(false), 2000);
      } else {
        // clipboard unavailable (permissions / insecure context): select so a
        // manual copy works
        selectAll();
      }
    });
  };

  return (
    <div className="ux-secret" role="status">
      <strong className="ux-secret__title">{title ?? "Copy this secret now."}</strong>
      <p className="ux-secret__body">
        {body ?? "This is the only time it is shown. It cannot be retrieved again."}
      </p>
      <pre
        className="ux-secret__block"
        ref={blockRef}
        onClick={selectAll}
        title="Click to select"
      >
        {secret}
      </pre>
      <div className="ux-secret__actions">
        <button type="button" className="btn btn--primary" onClick={copy}>
          {copiedFlash ? "Copied" : copyLabel ?? "Copy"}
        </button>
        {everCopied ? (
          <button type="button" className="btn btn--ghost" onClick={onDone}>
            Done
          </button>
        ) : (
          // P27 semantics on an uncopied dismiss: the secret is unrecoverable
          <ArmConfirm
            label="Done"
            armLabel="Dismiss without copying? The secret cannot be shown again."
            confirmLabel="Dismiss anyway"
            tone="warn"
            busyLabel="Dismissing..."
            onConfirm={async () => onDone()}
          />
        )}
      </div>
      {meta != null && <div className="ux-secret__meta">{meta}</div>}
    </div>
  );
}

export { DiffView } from "@/panels/uxFlow/diffView";
