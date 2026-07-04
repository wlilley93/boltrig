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
  type MouseEvent,
  type ReactNode,
} from "react";
import { api } from "@/api/client";
import type { InvokeResult } from "@/api/types";
import { setComposerPrefill } from "@/composerPrefill";
import { useSlideActive } from "@/deck/context";
import { navigate } from "@/router";
import { apiReason, CodeBlock } from "@/panels/shared";
import { AUDIT_STATUS, Hint, InfoCallout, StatusBadge } from "@/panels/ux";
import { copyText } from "@/panels/uxFlow/copyText";

import { ArmConfirm, useArmConfirm } from "@/panels/uxFlow/armConfirm";
export type { ArmTone, UseArmConfirm } from "@/panels/uxFlow/armConfirm";
export { ArmConfirm, useArmConfirm };

// --- SaveBar (N10, P17): the dirty-state bar pinned to the slide frame ------
// Pinned via position:sticky INSIDE the frame scroller, never fixed: the deck
// plane transform makes fixed resolve to the slide (reader-shell section 3).
// Render it as the last child of the slide's content.

export function SaveBar({
  dirty,
  saving,
  label,
  saveLabel,
  onSave,
  onDiscard,
  governed,
}: {
  dirty: boolean;
  saving: boolean;
  label: ReactNode; // "Unsaved changes to invoice-flow"
  saveLabel: ReactNode; // ignored when governed (amendment 2 fixes the copy)
  onSave: () => void;
  onDiscard: () => void | Promise<void>;
  // true when the save traverses a control.* verb: the FIRST submit always
  // 202s (dispatch.py:213), so the button says so and the foreshadow renders
  governed?: boolean;
}) {
  const discard = useArmConfirm(
    useCallback(async () => {
      await onDiscard();
    }, [onDiscard]),
  );
  if (!dirty && !saving) return null;
  return (
    <div className="ux-savebar" role="status">
      <div className="ux-savebar__text">
        <span className="ux-savebar__label">{label}</span>
        {governed && (
          <span className="ux-savebar__foreshadow">
            This is a high-consequence change. It will pause for a human
            approval before it takes effect.
          </span>
        )}
      </div>
      <div className="ux-savebar__actions">
        {discard.armed ? (
          <span className="ux-savebar__confirm" {...discard.containerProps}>
            <span className="ux-savebar__restate">
              Discard changes? Your edits since the last save are lost.
            </span>
            {discard.error && (
              <span className="ux-arm__error" role="alert">
                {discard.error}
              </span>
            )}
            <button
              type="button"
              className="btn btn--sm ux-btn--danger"
              disabled={discard.busy}
              onClick={discard.confirm}
            >
              {discard.busy ? "Discarding..." : "Confirm discard"}
            </button>
            <button
              type="button"
              className="btn btn--sm btn--ghost"
              disabled={discard.busy}
              onClick={discard.disarm}
            >
              Cancel
            </button>
          </span>
        ) : (
          <button
            type="button"
            className="btn btn--ghost"
            disabled={saving}
            onClick={discard.arm}
          >
            Discard
          </button>
        )}
        <button
          type="button"
          className="btn btn--primary"
          disabled={saving || !dirty}
          onClick={onSave}
        >
          {saving
            ? governed
              ? "Requesting..."
              : "Saving..."
            : governed
              ? "Request change"
              : saveLabel}
        </button>
      </div>
    </div>
  );
}

// --- Disclosure (N11, P18): summary + body, count discoverable collapsed ----

export function Disclosure({
  summary,
  changedCount,
  count,
  defaultOpen,
  open,
  onToggle,
  children,
}: {
  summary: ReactNode;
  // P18: non-default values must be discoverable without expanding
  changedCount?: number;
  count?: ReactNode; // free-form meta slot, e.g. "412 chars"
  defaultOpen?: boolean;
  open?: boolean; // controlled when set
  onToggle?: (open: boolean) => void;
  children: ReactNode;
}) {
  const [internalOpen, setInternalOpen] = useState(defaultOpen ?? false);
  const isOpen = open !== undefined ? open : internalOpen;
  const toggle = (e: MouseEvent<HTMLElement>) => {
    // this component owns the open state; the native toggle would fork it
    e.preventDefault();
    const next = !isOpen;
    if (open === undefined) setInternalOpen(next);
    onToggle?.(next);
  };
  return (
    <details className="ux-disclosure" open={isOpen}>
      <summary className="ux-disclosure__summary" onClick={toggle}>
        {summary}
        {changedCount !== undefined && changedCount > 0 && (
          <span className="ux-disclosure__count">{changedCount} changed</span>
        )}
        {count != null && <span className="ux-disclosure__count">{count}</span>}
      </summary>
      <div className="ux-disclosure__body">{children}</div>
    </details>
  );
}

// --- Skeleton (N13, P25): first-load shape, never during polls --------------
// The shimmer is pure CSS; the global reduce-motion rules zero its duration,
// leaving a static block. aria-hidden: a skeleton is never content.

export function Skeleton({
  variant,
  count,
}: {
  variant: "rows" | "cards" | "transcript";
  count?: number;
}) {
  const n = count ?? (variant === "cards" ? 3 : 4);
  return (
    <div className={`ux-skel ux-skel--${variant}`} aria-hidden="true">
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className="ux-skel__item" />
      ))}
    </div>
  );
}

// --- CoachMark (N12, P21 rung 5): one-time, persisted, never re-shown -------

export function CoachMark({ id, children }: { id: string; children: ReactNode }) {
  const storageKey = `boltrig.coach.${id}`;
  const [dismissed, setDismissed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(storageKey) !== null;
    } catch {
      return false; // storage unavailable: session-only dismissal below
    }
  });
  if (dismissed) return null;
  const dismiss = () => {
    try {
      localStorage.setItem(storageKey, "1");
    } catch {
      // storage unavailable: the state below still hides it for this session
    }
    setDismissed(true);
  };
  return (
    <div className="ux-coach">
      <InfoCallout tone="info">
        <div>{children}</div>
        <span className="ux-coach__actions">
          <button type="button" className="btn btn--sm btn--ghost" onClick={dismiss}>
            Got it
          </button>
        </span>
      </InfoCallout>
    </div>
  );
}

// --- GrantList: mono chips for grant/scope patterns, expandable beyond 8 ----
// Supersedes the fixed renderer in shared.tsx for long lists (PAT scopes,
// skill tool_grants); import from here when the list can exceed the cap.

export function GrantList({
  grants,
  limit,
}: {
  grants?: string[];
  limit?: number; // chips shown before "+n more"; default 8
}) {
  const [expanded, setExpanded] = useState(false);
  const max = limit ?? 8;
  if (!grants || grants.length === 0) {
    return <span className="muted">none</span>;
  }
  const shown = expanded ? grants : grants.slice(0, max);
  const hidden = grants.length - shown.length;
  return (
    <span className="ux-grants">
      {shown.map((g, i) => (
        <code className="tag" key={`${g}-${i}`}>
          {g}
        </code>
      ))}
      {hidden > 0 && (
        <button
          type="button"
          className="btn btn--sm btn--ghost"
          onClick={() => setExpanded(true)}
        >
          +{hidden} more
        </button>
      )}
      {expanded && grants.length > max && (
        <button
          type="button"
          className="btn btn--sm btn--ghost"
          onClick={() => setExpanded(false)}
        >
          show fewer
        </button>
      )}
    </span>
  );
}

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

// --- ByChat (N16, P32): the parity law made visible --------------------------
// Always-visible label per AMENDMENTS item 7. Prefills the chat composer with
// the phrase (one-shot module store) and moves the deck; never auto-sends.

export function ByChat({ phrase }: { phrase: string }) {
  return (
    <button
      type="button"
      className="btn btn--ghost btn--sm ux-bychat"
      title={phrase}
      onClick={() => {
        setComposerPrefill(phrase);
        navigate("/chat");
      }}
    >
      Do this in chat
    </button>
  );
}

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

// --- DiffView (N19): flat key-path diff of two plain objects ----------------
// ok/down TEXT tints only, never amber (L4).

interface DiffRow {
  path: string;
  kind: "changed" | "added" | "removed" | "unchanged";
  before?: string;
  after?: string;
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function showValue(v: unknown): string {
  try {
    return JSON.stringify(v) ?? "undefined";
  } catch {
    return String(v);
  }
}

function diffWalk(before: unknown, after: unknown, path: string, out: DiffRow[]): void {
  if (isPlainObject(before) && isPlainObject(after)) {
    const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])];
    for (const k of keys) {
      const p = path ? `${path}.${k}` : k;
      if (!(k in before)) out.push({ path: p, kind: "added", after: showValue(after[k]) });
      else if (!(k in after)) out.push({ path: p, kind: "removed", before: showValue(before[k]) });
      else diffWalk(before[k], after[k], p, out);
    }
    return;
  }
  if (Array.isArray(before) && Array.isArray(after)) {
    const len = Math.max(before.length, after.length);
    for (let i = 0; i < len; i++) {
      const p = `${path}[${i}]`;
      if (i >= before.length) out.push({ path: p, kind: "added", after: showValue(after[i]) });
      else if (i >= after.length) out.push({ path: p, kind: "removed", before: showValue(before[i]) });
      else diffWalk(before[i], after[i], p, out);
    }
    return;
  }
  const b = showValue(before);
  const a = showValue(after);
  out.push(
    b === a
      ? { path, kind: "unchanged", before: b, after: a }
      : { path, kind: "changed", before: b, after: a },
  );
}

export function DiffView({
  before,
  after,
  elideUnchanged,
}: {
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  elideUnchanged?: boolean; // default true
}) {
  const rows: DiffRow[] = [];
  diffWalk(before, after, "", rows);
  const visible = (elideUnchanged ?? true) ? rows.filter((r) => r.kind !== "unchanged") : rows;
  if (visible.length === 0) {
    return <p className="ux-hint">No changes.</p>;
  }
  return (
    <div className="ux-diff">
      {visible.map((r) => (
        <div key={`${r.path}:${r.kind}`} className={`ux-diff__row ux-diff__row--${r.kind}`}>
          <code className="ux-diff__path">{r.path}</code>
          {r.kind === "unchanged" ? (
            <code className="ux-diff__same">{r.after}</code>
          ) : (
            <>
              {r.kind !== "added" && <code className="ux-diff__before">{r.before}</code>}
              {r.kind === "changed" && <span className="ux-diff__arrow">-&gt;</span>}
              {r.kind !== "removed" && <code className="ux-diff__after">{r.after}</code>}
            </>
          )}
        </div>
      ))}
    </div>
  );
}
