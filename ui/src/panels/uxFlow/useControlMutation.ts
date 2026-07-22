import { useState } from "react";

import { api } from "@/api/client";
import type { InvokeResult } from "@/api/types";
import { apiReason } from "@/panels/shared";

export interface PendingControlMutation {
  id: string;
  params: Record<string, unknown>;
  context?: Record<string, unknown>;
}

interface ControlMutationOptions {
  verb: string;
  onApplied: (
    output: unknown,
    params: Record<string, unknown>,
    result: Extract<InvokeResult, { status: "ok" | "degraded" }>,
  ) => void;
}

export interface ControlMutationState {
  busy: boolean;
  error: string | null;
  pending: PendingControlMutation | null;
  invoke: (
    params: Record<string, unknown>,
    context?: Record<string, unknown>,
  ) => Promise<InvokeResult | null>;
  onPendingApplied: (result: InvokeResult) => void;
  onPendingDenied: (reason: string) => void;
  resetPending: () => void;
}

function rejectedReason(result: InvokeResult): string | null {
  if (result.status === "denied" || result.status === "error") {
    return result.reason;
  }
  return null;
}

/**
 * Run a high-consequence control-plane mutation without treating a 202 pause
 * as success. The exact sent params stay attached to the pending request so
 * PendingHumanCard can re-apply the identical mutation after approval.
 */
export function useControlMutation({
  verb,
  onApplied,
}: ControlMutationOptions): ControlMutationState {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingControlMutation | null>(null);

  async function invoke(
    params: Record<string, unknown>,
    context?: Record<string, unknown>,
  ): Promise<InvokeResult | null> {
    setBusy(true);
    setError(null);
    setPending(null);
    try {
      const result = await api.invoke({
        noun: "control",
        verb,
        params,
        ...(context ? { context } : {}),
      });
      if (result.status === "pending_human") {
        setPending({ id: result.hitl_request_id, params, context });
        return result;
      }
      const reason = rejectedReason(result);
      if (reason !== null) {
        setError(reason);
        return result;
      }
      if (result.status === "ok" || result.status === "degraded") {
        onApplied(result.output, params, result);
      }
      return result;
    } catch (err) {
      setError(apiReason(err));
      return null;
    } finally {
      setBusy(false);
    }
  }

  function onPendingApplied(result: InvokeResult) {
    if (pending === null) return;
    const reason = rejectedReason(result);
    if (reason !== null) {
      setError(reason);
      return;
    }
    if (result.status !== "ok" && result.status !== "degraded") return;
    const params = pending.params;
    setPending(null);
    onApplied(result.output, params, result);
  }

  function onPendingDenied(reason: string) {
    setError(reason);
  }

  function resetPending() {
    setPending(null);
  }

  return {
    busy,
    error,
    pending,
    invoke,
    onPendingApplied,
    onPendingDenied,
    resetPending,
  };
}

export function outputRecord(output: unknown): Record<string, unknown> {
  return output !== null && typeof output === "object" && !Array.isArray(output)
    ? (output as Record<string, unknown>)
    : {};
}
