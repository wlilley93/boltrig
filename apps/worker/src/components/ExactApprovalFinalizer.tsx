import { useState } from "react";

import { client } from "../client";

export type ExactApprovalFinalizationState =
  | "waiting"
  | "checking"
  | "invalidated"
  | "rejected"
  | "expired"
  | "consumed"
  | "unavailable"
  | null;

export type GovernedResult = {
  status?: string;
  hitl_request_id?: string;
  reason?: string;
};

export function governedResultReason(
  result: GovernedResult,
  fallback: string,
): string {
  return result.reason ?? fallback;
}

export interface GovernedRouteRefusal {
  status: "denied" | "error" | "unavailable" | "degraded";
  reason: string;
}

// Governed routes tolerate non-2xx statuses at the SDK layer, so a denial,
// kernel error, degraded control plane, or unknown-resource body arrives as a
// resolved value shaped nothing like the route's success record. A success
// receipt always carries run/record fields; a refusal never carries run_id.
export function governedRouteRefusal(
  result: unknown,
): GovernedRouteRefusal | null {
  if (!result || typeof result !== "object") return null;
  const body = result as Record<string, unknown>;
  if (typeof body.run_id === "string" && body.run_id) return null;
  if (
    body.status === "denied"
    || body.status === "error"
    || body.status === "unavailable"
    || body.status === "degraded"
  ) {
    return {
      status: body.status,
      reason: typeof body.reason === "string" && body.reason
        ? body.reason
        : `The kernel refused the request (${body.status}).`,
    };
  }
  if (typeof body.error === "string" && body.error) {
    return { status: "error", reason: body.error };
  }
  return null;
}

interface PendingExactMutation<TInput> {
  input: TInput;
  approvalId: string;
  label: string;
  invalidated: boolean;
}

export interface ExactApprovalFinalizerController<TInput, TResult extends GovernedResult> {
  state: ExactApprovalFinalizationState;
  label: string;
  busy: boolean;
  begin(input: TInput, result: GovernedResult, label: string): boolean;
  invalidate(): void;
  clear(): void;
  continueExact(): Promise<void>;
}

function cloneRouteInput<TInput>(input: TInput): TInput {
  // These controllers accept only typed JSON route inputs. Cloning their
  // serialized form prevents later form/object mutation from changing the
  // request that an independent human actually approved.
  return JSON.parse(JSON.stringify(input)) as TInput;
}

export function useExactApprovalFinalizer<
  TInput,
  TResult extends GovernedResult,
>({
  isCurrent,
  replay,
  isApplied = (result: TResult) => result.status === "ok",
  onApplied,
  onRefused,
  onUncertain,
}: {
  isCurrent(input: TInput): boolean;
  replay(input: TInput, approvalId: string): Promise<TResult>;
  isApplied?(result: TResult): boolean;
  onApplied(result: TResult, input: TInput): void | Promise<void>;
  onRefused?(result: TResult): void;
  onUncertain?(state: "consumed" | "unavailable"): void | Promise<void>;
}): ExactApprovalFinalizerController<TInput, TResult> {
  const [pending, setPending] = useState<PendingExactMutation<TInput> | null>(null);
  const [state, setState] = useState<ExactApprovalFinalizationState>(null);
  const [lastLabel, setLastLabel] = useState("Governed change");
  const [busy, setBusy] = useState(false);

  function begin(input: TInput, result: GovernedResult, label: string): boolean {
    if (result.status !== "pending_human") return false;
    setLastLabel(label);
    if (!result.hitl_request_id) {
      setPending(null);
      setState("unavailable");
      return true;
    }
    setPending({
      input: cloneRouteInput(input),
      approvalId: result.hitl_request_id,
      label,
      invalidated: false,
    });
    setState("waiting");
    return true;
  }

  function invalidate() {
    setPending((current) => (
      current === null ? null : { ...current, invalidated: true }
    ));
    setState((current) => (
      current === "waiting"
      || current === "checking"
      || current === "unavailable"
        ? "invalidated"
        : current
    ));
  }

  function clear() {
    setPending(null);
    setState(null);
  }

  async function refreshCanonicalAfterUncertainty(
    uncertainState: "consumed" | "unavailable",
  ) {
    try {
      await onUncertain?.(uncertainState);
    } catch {
      // The finalization receipt remains authoritative even when its optional
      // canonical refresh also fails. In particular, a consumed approval must
      // never regress to waiting or be treated as replayable.
    }
  }

  async function continueExact() {
    if (pending === null || pending.invalidated || !isCurrent(pending.input)) {
      setState("invalidated");
      return;
    }
    setBusy(true);
    setState("checking");
    try {
      const approval = await client.invokeApprovalState(pending.approvalId);
      if (approval.status === "pending") {
        setState("waiting");
        return;
      }
      if (
        approval.status === "rejected"
        || approval.status === "expired"
      ) {
        setState(approval.status);
        return;
      }
      if (approval.status === "consumed") {
        setState("consumed");
        await refreshCanonicalAfterUncertainty("consumed");
        return;
      }
      const result = await replay(pending.input, pending.approvalId);
      if (result.status === "pending_human") {
        if (!result.hitl_request_id) {
          setPending(null);
          setState("unavailable");
          return;
        }
        // A mutable resource may have changed after the first decision. The
        // kernel then refuses that stale fingerprint and issues a fresh exact
        // request. Retain the same cloned route input with only the new opaque
        // approval handle; otherwise the caller would strand a valid second
        // request with no lane able to apply it.
        setPending({
          input: pending.input,
          approvalId: result.hitl_request_id,
          label: pending.label,
          invalidated: false,
        });
        setState("waiting");
        return;
      }
      if (!isApplied(result)) {
        onRefused?.(result);
        setState("invalidated");
        return;
      }
      await onApplied(result, pending.input);
      setPending(null);
      setState(null);
    } catch {
      setState("unavailable");
      await refreshCanonicalAfterUncertainty("unavailable");
    } finally {
      setBusy(false);
    }
  }

  return {
    state,
    label: pending?.label ?? lastLabel,
    busy,
    begin,
    invalidate,
    clear,
    continueExact,
  };
}

export function ExactApprovalFinalizer<TInput, TResult extends GovernedResult>({
  controller,
}: {
  controller: ExactApprovalFinalizerController<TInput, TResult>;
}) {
  if (controller.state === null) return null;
  const copy = finalizationCopy(controller.state, controller.label);
  return (
    <div
      className={`notice exact-approval-finalizer ${controller.state}`}
      role="status"
    >
      <strong>{copy[0]}</strong>
      <p>{copy[1]}</p>
      {(controller.state === "waiting"
        || controller.state === "unavailable") && (
        <button
          className="secondary-button"
          type="button"
          disabled={controller.busy}
          onClick={() => void controller.continueExact()}
        >
          Check approval and apply exact change
        </button>
      )}
    </div>
  );
}

function finalizationCopy(
  state: Exclude<ExactApprovalFinalizationState, null>,
  label: string,
): [string, string] {
  if (state === "waiting") {
    return [
      `${label} is waiting for approval`,
      "After an independent decision in the originating chat, continue only the exact component-held route inputs.",
    ];
  }
  if (state === "checking") {
    return ["Checking approval…", "No mutation is inferred until the kernel responds."];
  }
  if (state === "rejected") {
    return [`${label} was rejected`, "Nothing was applied."];
  }
  if (state === "expired") {
    return [`${label} approval expired`, "The expired decision cannot authorize a mutation."];
  }
  if (state === "consumed") {
    return [
      `${label} approval was already consumed`,
      "Refresh the canonical resource before requesting another change.",
    ];
  }
  if (state === "invalidated") {
    return [
      `${label} changed`,
      "The form, selection or canonical resource changed. The old approval will not be applied.",
    ];
  }
  return [
    `${label} approval is unavailable`,
    "No mutation is inferred. Check again when caller-owned approval state is available.",
  ];
}
