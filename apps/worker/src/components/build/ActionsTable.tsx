import { useEffect, useMemo, useRef, useState } from "react";
import { BoltrigApiError, type VerbInventoryItem } from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import { Unavailable } from "../Shell";

import "./build.css";

// The read-first Actions table (design lines 851-875, tab "actions"): one row
// per caller-visible verb from client.verbs(). Every cell states only what the
// inventory record carries - description, the binding it executes through, and
// the consequence-derived needs-you word. The design's "Used N x" column has no
// endpoint anywhere, so it is omitted rather than invented.

type TableState = "loading" | "ready" | "denied" | "unavailable";

export function ActionsTable({ onOpen }: { onOpen(verbId: string): void }) {
  const [verbs, setVerbs] = useState<VerbInventoryItem[]>([]);
  const [state, setState] = useState<TableState>("loading");
  const [filter, setFilter] = useState("");
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

  const visible = useMemo(() => {
    const term = filter.trim().toLowerCase();
    return term
      ? verbs.filter((verb) => (
        `${verb.id} ${verb.description} ${verb.binding?.target_ref ?? ""}`.toLowerCase().includes(term)
      ))
      : verbs;
  }, [filter, verbs]);

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
        {visible.map((verb) => {
          const runnable = verb.is_active && verb.noun_status === "active";
          const needsYou = verb.consequence === "high";
          return (
            <button className="console-row" key={verb.id} onClick={() => onOpen(verb.id)} type="button">
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
              <span className="console-state" data-tone={needsYou ? "asking" : undefined}>
                {needsYou ? "always" : "no"}
              </span>
              <span className="console-far">{runnable ? "on" : verb.status === "archived" ? "archived" : "off"}</span>
            </button>
          );
        })}
        {visible.length === 0 && (
          <div className="console-row"><span className="console-row-sub">No actions match that filter.</span></div>
        )}
      </div>
      <p className="console-foot">
        Anything not on this list simply cannot happen: an unknown action is
        refused, not guessed at. &ldquo;Always&rdquo; comes from the action&rsquo;s high
        consequence and cannot be bypassed; deployment policy can add asking to
        any action, and can never remove it. Archived actions stay listed and
        cannot run.
      </p>
    </div>
  );
}
