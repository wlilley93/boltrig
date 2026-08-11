import { useEffect, useRef, useState } from "react";
import { BoltrigApiError, type MemoryFactView } from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import {
  ExactApprovalFinalizer,
  useExactApprovalFinalizer,
} from "../ExactApprovalFinalizer";
import { Unavailable } from "../Shell";

import "./knowledge.css";

// The Knowledge "What it remembers" tab (design lines 979-995): the browse
// slice of the memory surface, with a governed per-row Forget. Recall,
// remember and screened ingestion stay on the Memory route - the design gives
// them no home here and dropping them would lose working governed surfaces.
// Every provenance sentence below is assembled from the recorded fields
// (source_kind, source_ref, created_at); nothing is inferred.

type TabState = "loading" | "ready" | "denied" | "unavailable";

function factTitle(content: unknown): string {
  if (typeof content === "string") return content;
  try {
    return JSON.stringify(content);
  } catch {
    return String(content);
  }
}

function learnedAge(value: string | null | undefined): string | null {
  if (!value) return null;
  const time = Date.parse(value);
  if (!Number.isFinite(time)) return null;
  const days = Math.max(0, Math.floor((Date.now() - time) / 86_400_000));
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 14) return `${days} days ago`;
  if (days < 60) return `${Math.round(days / 7)} weeks ago`;
  return `${Math.round(days / 30)} months ago`;
}

function provenanceSentence(fact: MemoryFactView): string {
  const { source_kind, source_ref, created_at } = fact.provenance;
  const parts: string[] = [];
  const age = learnedAge(created_at);
  if (source_kind) {
    parts.push(
      `${age ? `learned ${age}, ` : "learned "}from ${source_kind.replaceAll("_", " ")}`
      + (source_ref ? ` ${source_ref}` : ""),
    );
  } else {
    // The kernel records no source for directly-recorded facts; this mirrors
    // the browse surface's "direct" rendering in plain words.
    parts.push(age ? `recorded directly, ${age}` : "recorded directly");
  }
  parts.push(fact.owner_scope);
  return parts.join(" · ");
}

export function RemembersTab() {
  const [facts, setFacts] = useState<MemoryFactView[]>([]);
  const [scopes, setScopes] = useState<string[]>([]);
  const [state, setState] = useState<TabState>("loading");
  const [message, setMessage] = useState("");
  const [armed, setArmed] = useState<string | null>(null);
  const loaded = useRef(false);
  const forgetFinalizer = useExactApprovalFinalizer<
    { target: string },
    Awaited<ReturnType<typeof client.memoryForget>>
  >({
    isCurrent: (input) => facts.some((fact) => fact.id === input.target),
    replay: (input, approvalId) => client.memoryForget({ target: input.target }, approvalId),
    onApplied: () => {
      setMessage("The selected fact was forgotten.");
      refresh();
    },
    onRefused: (result) => {
      setMessage(result.reason ?? "The approved forget was not applied.");
    },
    onUncertain: () => refresh(),
  });

  function refresh() {
    forgetFinalizer.invalidate();
    void client.memoryFacts({ limit: 60 })
      .then((result) => {
        setFacts(result.facts);
        setScopes(result.scopes);
        loaded.current = true;
        setState("ready");
      })
      .catch((reason) => {
        if (loaded.current) return;
        setState(
          reason instanceof BoltrigApiError && (reason.status === 401 || reason.status === 403)
            ? "denied"
            : "unavailable",
        );
      });
  }
  useEffect(refresh, []);

  async function forget(fact: MemoryFactView) {
    if (armed !== fact.id) {
      setArmed(fact.id);
      return;
    }
    forgetFinalizer.invalidate();
    const input = { target: fact.id };
    const result = await client.memoryForget(input);
    setArmed(null);
    if (forgetFinalizer.begin(input, result, "Memory erasure")) {
      setMessage("Forgetting this fact is waiting for approval in the originating chat.");
      return;
    }
    setMessage(result.reason ?? (
      result.status === "ok"
        ? "The selected fact was forgotten."
        : `Forget status: ${result.status}.`
    ));
    forgetFinalizer.clear();
    if (result.status === "ok") refresh();
  }

  if (state === "loading") {
    return <Unavailable title="Loading remembered facts">Loading facts in your permitted memory scopes.</Unavailable>;
  }
  if (state === "denied") {
    return <Unavailable title="Memory access denied">Your current role cannot browse memory in this workspace.</Unavailable>;
  }
  if (state === "unavailable") {
    return <Unavailable title="Memory unavailable">The governed memory service could not be reached.</Unavailable>;
  }

  return (
    <div className="console-table-wrap">
      {message && <p className="notice" role="status">{message}</p>}
      <ExactApprovalFinalizer controller={forgetFinalizer} />
      {facts.length === 0 ? (
        <Unavailable title="Nothing remembered yet">Facts the assistant remembers, with their provenance, will appear here.</Unavailable>
      ) : (
        <div className="console-table">
          {facts.map((fact) => (
            <div className="console-row" key={fact.id}>
              <span className="console-row-main">
                <span className="console-row-title"><span>{factTitle(fact.content)}</span></span>
                <span className="console-row-sub">{provenanceSentence(fact)}</span>
              </span>
              <button
                className="knowledge-forget"
                data-armed={armed === fact.id ? "true" : undefined}
                onClick={() => void forget(fact)}
                type="button"
              >
                {armed === fact.id ? "Confirm forget" : "Forget"}
              </button>
            </div>
          ))}
        </div>
      )}
      <p className="console-foot">
        {scopes.length > 0
          ? `Scoped to ${scopes.join(", ")}. Facts outside these scopes are not shown or recalled here. `
          : ""}
        Recall, remember and screened ingestion live in <a href="#/memory">Memory</a>.
      </p>
    </div>
  );
}
