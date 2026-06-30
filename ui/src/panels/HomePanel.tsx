// The capability-aware HOME / dashboard: the default landing. It does not own
// any data of its own; it reflects the caller's actual scoped state (approvals
// awaiting them, their recent runs, work in flight, and the verbs they are
// scoped to) and LINKS into the real panels (navigate) and the Run drawer
// (openRun) rather than duplicating their logic. Gates here are cosmetic; the
// server is the authoritative gate on every action.

import { useMemo } from "react";

import { AUTHOR_ROLES } from "../App";
import { api } from "../api/client";
import type { RunRow, VerbInfo, WorkStatus } from "../api/types";
import { useIdentity } from "../identity";
import { navigate } from "../router";
import { useFetch } from "../useFetch";
import { RunLink } from "./shared";

// The lanes that read as "in flight" for the compact count summary; mirrors the
// Kanban board order. Done / failed are terminal so they sit at the end.
const WORK_LANES: ReadonlyArray<{ status: WorkStatus; label: string }> = [
  { status: "in_flight", label: "In flight" },
  { status: "pending", label: "Pending" },
  { status: "blocked", label: "Blocked" },
  { status: "awaiting_human", label: "Awaiting human" },
  { status: "done", label: "Done" },
  { status: "failed", label: "Failed" },
];

// "Needs you": pending human-in-the-loop, polled so the home stays current. We
// surface the top few questions and link the section into the Approvals tab,
// where they are answered inline (answering here is out of scope).
function NeedsYou() {
  const hitl = useFetch(() => api.hitl(), [], 8000);
  const requests = hitl.data?.requests ?? [];
  const top = requests.slice(0, 3);

  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>Needs you</h3>
        <span className="muted">{requests.length} pending</span>
      </div>
      <div className="list-card__body">
        {hitl.loading && !hitl.data && (
          <p className="muted">Loading approvals...</p>
        )}
        {hitl.error && (
          <p className="error">Failed to load approvals: {hitl.error}</p>
        )}
        {!hitl.loading && !hitl.error && requests.length === 0 && (
          <p className="muted">Nothing is waiting on you right now.</p>
        )}
        {top.map((req) => (
          <button
            key={req.id}
            className="palette-row"
            title="Open Approvals"
            onClick={() => navigate("/approvals")}
          >
            <span className="home-line">
              <span className={`badge badge--type badge--type-${req.type}`}>
                {req.type}
              </span>
              <span className="home-line__text">
                {req.question || "(no question)"}
              </span>
            </span>
          </button>
        ))}
        {requests.length > top.length && (
          <button className="btn btn--ghost" onClick={() => navigate("/approvals")}>
            View all {requests.length}
          </button>
        )}
      </div>
    </div>
  );
}

// "Recent runs": the few most recent runs, each a RunLink that raises the global
// Run drawer (openRun) so its live events, tree and cost are one click away.
function RecentRuns() {
  const runs = useFetch(() => api.runs(), [], 0);
  const top: RunRow[] = (runs.data?.runs ?? []).slice(0, 5);

  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>Recent runs</h3>
        <button className="btn" onClick={() => runs.reload()}>
          Refresh
        </button>
      </div>
      <div className="list-card__body">
        {runs.loading && !runs.data && <p className="muted">Loading runs...</p>}
        {runs.error && (
          <p className="error">Failed to load runs: {runs.error}</p>
        )}
        {!runs.loading && !runs.error && top.length === 0 && (
          <p className="muted">No runs yet.</p>
        )}
        {top.map((run) => (
          <div className="row-line" key={run.run_id ?? run.work_item}>
            <span className="home-line__text">{run.intent || "(no intent)"}</span>
            <span className="kv">
              <span className="badge">{run.status}</span>
              {run.run_id ? (
                <RunLink runId={run.run_id} label="open" />
              ) : (
                <span className="muted">no run</span>
              )}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// "Work in flight": a compact count of work items by status (the Kanban lanes,
// just counts), linking into the full board.
function WorkInFlight() {
  const work = useFetch(() => api.work(), [], 0);
  const items = work.data?.items ?? [];

  const counts = useMemo(() => {
    const map = new Map<WorkStatus, number>();
    for (const lane of WORK_LANES) map.set(lane.status, 0);
    for (const item of items) {
      map.set(item.status, (map.get(item.status) ?? 0) + 1);
    }
    return map;
  }, [items]);

  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>Work in flight</h3>
        <span className="muted">{items.length} item(s)</span>
      </div>
      <div className="list-card__body">
        {work.loading && !work.data && <p className="muted">Loading work...</p>}
        {work.error && (
          <p className="error">Failed to load work: {work.error}</p>
        )}
        {!work.loading && !work.error && (
          <>
            <div className="home-metrics">
              {WORK_LANES.map((lane) => (
                <div className="home-metric" key={lane.status}>
                  <span className="home-metric__count">
                    {counts.get(lane.status) ?? 0}
                  </span>
                  <span className="home-metric__label">{lane.label}</span>
                </div>
              ))}
            </div>
            <button className="btn btn--ghost" onClick={() => navigate("/kanban")}>
              Open the board
            </button>
          </>
        )}
      </div>
    </div>
  );
}

// "What I can do": the capability-aware heart of the home. It reflects the
// caller's actual scoped verbs from /v1/capabilities (not a hardcoded menu):
// the total count and a per-noun breakdown, linking into the Router.
function WhatICanDo() {
  const caps = useFetch(() => api.capabilities(), [], 0);
  const verbs = caps.data?.verbs ?? [];

  const byNoun = useMemo(() => {
    const map = new Map<string, number>();
    for (const v of verbs as VerbInfo[]) {
      const noun = v.noun || "(unspecified)";
      map.set(noun, (map.get(noun) ?? 0) + 1);
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [verbs]);

  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>What I can do</h3>
        <span className="muted">{verbs.length} verb(s)</span>
      </div>
      <div className="list-card__body">
        {caps.loading && !caps.data && (
          <p className="muted">Loading capabilities...</p>
        )}
        {caps.error && (
          <p className="error">Failed to load capabilities: {caps.error}</p>
        )}
        {!caps.loading && !caps.error && byNoun.length === 0 && (
          <p className="muted">No verbs are scoped to this identity.</p>
        )}
        {byNoun.length > 0 && (
          <p className="muted">
            You are scoped to {verbs.length} verb(s) across {byNoun.length}{" "}
            noun(s).
          </p>
        )}
        <div className="kv">
          {byNoun.map(([noun, count]) => (
            <span className="tag" key={noun}>
              {noun} ({count})
            </span>
          ))}
        </div>
        <button className="btn btn--ghost" onClick={() => navigate("/router")}>
          Browse the router
        </button>
      </div>
    </div>
  );
}

// "Quick start": jump-off actions. Everyone gets a new conversation and the
// router; authoring quick-starts (a new workflow) only show for AUTHOR_ROLES,
// mirroring App's tab gates. The gates are cosmetic only; the server is the
// authoritative gate on every action. "New workflow" lands on the Studio, which
// hosts the workflow canvas (there is no standalone /canvas tab).
function QuickStart({ role }: { role: string }) {
  const canAuthor = AUTHOR_ROLES.has(role);
  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>Quick start</h3>
      </div>
      <div className="list-card__body">
        <div className="home-actions">
          <button className="btn btn--primary" onClick={() => navigate("/chat")}>
            New conversation
          </button>
          {canAuthor && (
            <button className="btn" onClick={() => navigate("/studio")}>
              New workflow
            </button>
          )}
          <button className="btn" onClick={() => navigate("/router")}>
            Browse capabilities
          </button>
        </div>
      </div>
    </div>
  );
}

export function HomePanel() {
  const identity = useIdentity();

  return (
    <section className="panel">
      <div className="panel__head">
        <h2>Home</h2>
        <span className="muted">
          {identity.subject} @ {identity.tenant}
        </span>
      </div>

      <div className="cols">
        <NeedsYou />
        <RecentRuns />
        <WorkInFlight />
        <WhatICanDo />
        <QuickStart role={identity.role} />
      </div>
    </section>
  );
}
