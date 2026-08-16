import { useEffect, useState } from "react";
import type {
  ApprovalPosture,
  VerbInventoryItem,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";

export interface ActionApprovalPolicy {
  blocking: Set<string> | null;
  posture: ApprovalPosture | null;
}

export function useActionApprovalPolicy(): ActionApprovalPolicy {
  const [blocking, setBlocking] = useState<Set<string> | null>(null);
  const [posture, setPosture] = useState<ApprovalPosture | null>(null);

  useEffect(() => {
    void client.hitlPolicy()
      .then((result) => setBlocking(new Set(result.policy.blocking_verbs)))
      .catch(() => setBlocking(null));
  }, []);

  useEffect(() => {
    if (typeof client.approvalPosture !== "function") {
      setPosture(null);
      return;
    }
    void client.approvalPosture()
      .then((result) => setPosture(result.posture))
      .catch(() => setPosture(null));
  }, []);

  return { blocking, posture };
}

function approvalLabel(
  verb: VerbInventoryItem,
  policy: ActionApprovalPolicy,
): "always" | "no" | "not known" {
  if (policy.blocking?.has(verb.id)) return "always";

  const postureControlled = verb.binding?.target_type === "adapter"
    && verb.binding.target_ref !== "control";
  if (!postureControlled) {
    if (verb.consequence === "high") return "always";
    return policy.blocking === null ? "not known" : "no";
  }

  if (policy.posture === "always_ask") return "always";
  if (policy.blocking === null || policy.posture === null) return "not known";
  if (policy.posture === "full_access") return "no";
  return verb.consequence === "high" ? "always" : "no";
}

export function ActionInventoryRow({
  onOpen,
  policy,
  verb,
}: {
  onOpen(verbId: string): void;
  policy: ActionApprovalPolicy;
  verb: VerbInventoryItem;
}) {
  const runnable = verb.is_active && verb.noun_status === "active";
  const approval = approvalLabel(verb, policy);
  return (
    <button className="console-row" onClick={() => onOpen(verb.id)} type="button">
      <span
        aria-hidden
        className="console-pip"
        data-tone={runnable ? verb.consequence : "off"}
      />
      <span className="console-row-main">
        <span className="console-row-title"><span>{verb.id}</span></span>
        <span className="console-row-sub">
          {verb.description || "No description recorded"}
        </span>
      </span>
      <span className="console-cell">
        {verb.binding
          ? `${verb.binding.target_ref}${verb.binding.target_type === "agent" ? " (agent)" : ""}`
          : "Not bound — cannot run"}
      </span>
      <span className="console-state" data-tone={approval === "always" ? "asking" : undefined}>
        {approval}
      </span>
      <span className="console-far">
        {runnable ? "on" : verb.status === "archived" ? "archived" : "off"}
      </span>
    </button>
  );
}
