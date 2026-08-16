import { useEffect, useState } from "react";
import type {
  HitlEntry,
  InvokeApprovalStateResponse,
  QuestionEntry,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import { LiveQuestionCard } from "../LiveQuestionCard";
import { InlineApproval } from "./InlineApproval";

type Decision =
  | { kind: "approval"; entry: HitlEntry }
  | { kind: "question"; entry: QuestionEntry };

type LoadState = InvokeApprovalStateResponse["status"] | "loading" | "unavailable";

/** Reconcile a recorded decision card with the canonical HITL record.
 *
 * A chat turn can be complete while a governed action is still waiting. That
 * is the normal shape of a routine run: the transcript is durable, and the
 * approval resumes from its opaque request id. We therefore never infer
 * answerability from the age of the message. */
export function PersistedDecision({ decision, tech, onResolved }: {
  decision: Decision;
  tech: boolean;
  onResolved?(): void;
}) {
  const requestId = decision.kind === "approval"
    ? decision.entry.hitlRequestId
    : decision.entry.questionId;
  const [state, setState] = useState<LoadState>("loading");
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let current = true;
    setState("loading");
    void client.invokeApprovalState(requestId).then(
      (result) => { if (current) setState(result.status); },
      () => { if (current) setState("unavailable"); },
    );
    return () => { current = false; };
  }, [reload, requestId]);

  if (state === "pending") {
    return decision.kind === "approval"
      ? <InlineApproval entry={decision.entry} tech={tech} onResolved={onResolved} />
      : <LiveQuestionCard question={decision.entry} onAnswered={onResolved} />;
  }
  if (state === "loading" || state === "unavailable") {
    return <DecisionStatus
      label={decisionLabel(decision)}
      unavailable={state === "unavailable"}
      onRetry={() => setReload((value) => value + 1)}
    />;
  }
  if (decision.kind === "approval") {
    return <ResolvedApproval decision={decision} state={state} tech={tech} />;
  }
  return <div className="approval-card live-question" data-phase="replay">
    <strong>Question from this run</strong>
    <p>{decision.entry.prompt}</p>
    <p className="muted small">This request is {state} and is no longer answerable.</p>
  </div>;
}

function ResolvedApproval({ decision, state, tech }: {
  decision: Extract<Decision, { kind: "approval" }>;
  state: "approved" | "rejected" | "expired" | "consumed";
  tech: boolean;
}) {
  return <div className="inline-approval" data-phase="replay">
    <div className="inline-approval-head">
      <span aria-hidden />
      <strong>{decision.entry.question}</strong>
      {tech && decision.entry.verb && <span className="verb-chip">{decision.entry.verb}</span>}
    </div>
    <div className="inline-approval-body">
      <p className="muted small">This request is {state} and is no longer answerable.</p>
    </div>
  </div>;
}

function DecisionStatus({ label, unavailable, onRetry }: {
  label: string;
  unavailable: boolean;
  onRetry(): void;
}) {
  return <div className="approval-card" data-phase="reconciling">
    <strong>{label}</strong>
    <p className="muted small">
      {unavailable
        ? "The current request state could not be verified. It remains read-only."
        : "Checking whether this request still needs an answer…"}
    </p>
    {unavailable && <button className="secondary-button" onClick={onRetry} type="button">
      Check again
    </button>}
  </div>;
}

function decisionLabel(decision: Decision): string {
  return decision.kind === "approval"
    ? decision.entry.question
    : "Question from this run";
}
