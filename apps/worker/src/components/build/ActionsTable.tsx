import { useEffect, useMemo, useRef, useState } from "react";
import { BoltrigApiError, type VerbInventoryItem } from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import { Unavailable } from "../Shell";
import {
  ActionInventoryRow,
  useActionApprovalPolicy,
} from "./ActionApprovalPresentation";

import "./build.css";

// The read-first Actions table (design lines 851-875, tab "actions"): one row
// per caller-visible verb from client.verbs(). Every cell states only what the
// inventory record carries - description and the binding it executes through.
// The design's "Used N x" column has no endpoint anywhere, so it is omitted
// rather than invented.
//
// "Needs you" has three sources: authored consequence, deployment HITL policy,
// and the caller-owned delegated-agent posture. Reading only one would print a
// flat answer either of the other two can falsify, so unknown inputs stay
// visibly unknown instead of being guessed client-side.

type TableState = "loading" | "ready" | "denied" | "unavailable";

function ActionTableFoot({ unknown }: { unknown: boolean }) {
  return <p className="console-foot">
    Anything not on this list simply cannot happen: an unknown action is
    refused, not guessed at. &ldquo;Always&rdquo; reflects the deployment blocklist,
    the selected delegated-agent posture, and non-waivable control or agent
    gates. Full access removes prompts only for already-granted external
    adapters; it never widens authority or changes direct-human controls.
    {unknown && " One or more approval inputs could not be read here, so affected actions read “not known” rather than guessing."}
    {" "}Archived actions stay listed and cannot run.
  </p>;
}

function filterVerbs(verbs: VerbInventoryItem[], filter: string) {
  const term = filter.trim().toLowerCase();
  return term
    ? verbs.filter((verb) => (
      `${verb.id} ${verb.description} ${verb.binding?.target_ref ?? ""}`.toLowerCase().includes(term)
    ))
    : verbs;
}

export function ActionsTable({ onOpen }: { onOpen(verbId: string): void }) {
  const [verbs, setVerbs] = useState<VerbInventoryItem[]>([]);
  const [state, setState] = useState<TableState>("loading");
  const [filter, setFilter] = useState("");
  const approvalPolicy = useActionApprovalPolicy();
  const loaded = useRef(false);

  useEffect(() => {
    void client.verbs()
      .then((result) => {
        setVerbs(result.verbs);
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
  }, []);

  const visible = useMemo(() => filterVerbs(verbs, filter), [filter, verbs]);

  if (state === "loading") {
    return <Unavailable title="Loading actions">Reading the caller-visible verb inventory.</Unavailable>;
  }
  if (state === "denied") {
    return <Unavailable title="Actions access denied">Your current role cannot read the authored verb inventory.</Unavailable>;
  }
  if (state === "unavailable") {
    return <Unavailable title="Actions unavailable">The caller-scoped capability registry could not be reached.</Unavailable>;
  }
  if (verbs.length === 0) {
    return <Unavailable title="No actions defined">The registry has no verb records, so nothing can be carried out.</Unavailable>;
  }

  return (
    <div className="console-table-wrap">
      <input
        aria-label="Filter actions"
        className="field-control"
        onChange={(event) => setFilter(event.target.value)}
        placeholder="Filter by name, description or system…"
        value={filter}
      />
      <div className="console-table">
        <div className="console-table-head">
          <span aria-hidden className="console-pip" style={{ background: "transparent" }} />
          <span style={{ flex: 1 }}>Action</span>
          <span className="console-cell">Where it comes from</span>
          <span className="console-state">Needs you</span>
          <span className="console-far">Status</span>
        </div>
        {visible.map((verb) => (
          <ActionInventoryRow
            key={verb.id}
            onOpen={onOpen}
            policy={approvalPolicy}
            verb={verb}
          />
        ))}
        {visible.length === 0 && (
          <div className="console-row"><span className="console-row-sub">No actions match that filter.</span></div>
        )}
      </div>
      <ActionTableFoot
        unknown={approvalPolicy.blocking === null || approvalPolicy.posture === null}
      />
    </div>
  );
}
