import { useCallback, useEffect, useState } from "react";
import type {
  CapabilityBindingStatus,
  CapabilityBindingView,
  InvokeResult,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import {
  governedResultReason,
  useExactApprovalFinalizer,
} from "../ExactApprovalFinalizer";

/**
 * The review queue's state, its governed decision lane, and nothing about how
 * it looks.
 *
 * Separated from the panel because approve and reject are HIGH-consequence
 * verbs whose approval handling is the part worth reading on its own: which
 * input the approval is bound to, what happens when the answer is uncertain,
 * and what the panel is allowed to claim afterwards. Buried inside a component
 * body it reads as plumbing.
 */

export type QueueFilter = CapabilityBindingStatus | "all";
export type Decision = "approve" | "reject";
export type QueueState = "loading" | "ready" | "unavailable";

export interface BindingDecision {
  bindingId: string;
  decision: Decision;
  request: {
    noun: string;
    verb: string;
    idempotency_key: string;
    params: { binding_id: string };
  };
}

function decisionInput(bindingId: string, decision: Decision): BindingDecision {
  return {
    bindingId,
    decision,
    request: {
      noun: "control",
      verb: `control.capability_binding.${decision}`,
      idempotency_key: crypto.randomUUID(),
      params: { binding_id: bindingId },
    },
  };
}

export function useCapabilityReviewQueue(filter: QueueFilter) {
  const [bindings, setBindings] = useState<CapabilityBindingView[]>([]);
  const [state, setState] = useState<QueueState>("loading");
  const [needsReview, setNeedsReview] = useState(0);
  const [message, setMessage] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const result = await client.capabilityBindings(
        filter === "all" ? undefined : filter,
      );
      setBindings(result.bindings);
      setNeedsReview(result.needs_review);
      setState("ready");
    } catch {
      setState("unavailable");
    }
  }, [filter]);

  useEffect(() => {
    void load();
  }, [load]);

  const finalizer = useExactApprovalFinalizer<BindingDecision, InvokeResult>({
    // The BINDING is the identity, not the row's position in a list that
    // reloads under it: an approval minted for one binding must never be
    // redeemed against whatever now sits where that row was.
    isCurrent: (input) => bindings.some((row) => row.binding_id === input.bindingId),
    replay: (input, approvalId) => client.invoke({
      ...input.request,
      approval_id: approvalId,
    }),
    onApplied: async (_result, input) => {
      setMessage(input.decision === "approve"
        ? `${input.bindingId} approved. Its canonical verb is now routable.`
        : `${input.bindingId} refused. The claim stays on the record.`);
      await load();
    },
    onRefused: (result) => {
      setMessage(governedResultReason(result, "The approved decision was refused."));
    },
    onUncertain: async () => {
      await load();
      setMessage("The queue was refreshed; no decision is inferred.");
    },
  });

  async function decide(row: CapabilityBindingView, decision: Decision) {
    finalizer.invalidate();
    setBusyId(row.binding_id);
    setMessage("");
    const input = decisionInput(row.binding_id, decision);
    try {
      const result = await client.invoke(input.request);
      if (finalizer.begin(input, result, `${row.capability_id} ${decision}`)) {
        setMessage("The decision is waiting for approval in the originating chat.");
        return;
      }
      if (result.status !== "ok" && result.status !== "degraded") {
        setMessage(`Not changed: ${governedResultReason(result, result.status)}.`);
        return;
      }
      await load();
      setMessage(decision === "approve"
        ? `${row.capability_id} approved.`
        : `${row.capability_id} refused.`);
    } catch {
      setMessage("The decision was not recorded.");
    } finally {
      setBusyId(null);
    }
  }

  return { bindings, busyId, decide, finalizer, message, needsReview, state };
}
