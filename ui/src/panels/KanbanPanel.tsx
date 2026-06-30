// US-WRK-03: a board of work items in status lanes. Each card shows intent,
// source, confidence, the convergent flag, owner and a handle to its
// hatchet_run_id, with a trace action that pulls the audit execution tree.

import { api } from "../api/client";
import type { WorkItem, WorkStatus } from "../api/types";
import { openRun } from "../router";
import { useFetch } from "../useFetch";

const LANES: ReadonlyArray<{ status: WorkStatus; label: string }> = [
  { status: "pending", label: "Pending" },
  { status: "in_flight", label: "In flight" },
  { status: "blocked", label: "Blocked" },
  { status: "awaiting_human", label: "Awaiting human" },
  { status: "done", label: "Done" },
  { status: "failed", label: "Failed" },
];

function confidenceText(c: WorkItem["confidence"]): string {
  if (c === null || c === undefined) return "n/a";
  return `${Math.round(c * 100)}%`;
}

function WorkCard({
  item,
  onTrace,
}: {
  item: WorkItem;
  onTrace: (runId: string) => void;
}) {
  return (
    <article className="card">
      <div className="card__intent">{item.intent || "(no intent)"}</div>
      <dl className="card__meta">
        <div>
          <dt>source</dt>
          <dd>{item.source ?? "n/a"}</dd>
        </div>
        <div>
          <dt>owner</dt>
          <dd>{item.owner_member ?? "unassigned"}</dd>
        </div>
        <div>
          <dt>confidence</dt>
          <dd>{confidenceText(item.confidence)}</dd>
        </div>
        <div>
          <dt>convergent</dt>
          <dd>{item.convergent ? "yes" : "no"}</dd>
        </div>
      </dl>
      <div className="card__foot">
        {item.hatchet_run_id ? (
          <button
            className="run-handle"
            title="View audit execution tree"
            onClick={() => onTrace(item.hatchet_run_id as string)}
          >
            run: <code>{item.hatchet_run_id}</code>
          </button>
        ) : (
          <span className="muted">no run</span>
        )}
      </div>
    </article>
  );
}

export function KanbanPanel() {
  const work = useFetch(() => api.work(), [], 10000);

  const items = work.data?.items ?? [];
  const byStatus = new Map<WorkStatus, WorkItem[]>();
  for (const lane of LANES) byStatus.set(lane.status, []);
  for (const item of items) {
    const bucket = byStatus.get(item.status);
    if (bucket) bucket.push(item);
    else byStatus.set(item.status, [item]);
  }

  return (
    <section className="panel">
      <div className="panel__head">
        <h2>Kanban</h2>
        <div className="panel__actions">
          <span className="muted">{items.length} item(s)</span>
          <button className="btn" onClick={() => work.reload()}>
            Refresh
          </button>
        </div>
      </div>

      {work.loading && !work.data && <p className="muted">Loading work items...</p>}
      {work.error && <p className="error">Failed to load work: {work.error}</p>}

      <div className="board">
        {LANES.map((lane) => {
          const laneItems = byStatus.get(lane.status) ?? [];
          return (
            <div className="lane" key={lane.status}>
              <div className={`lane__head lane__head--${lane.status}`}>
                <span>{lane.label}</span>
                <span className="lane__count">{laneItems.length}</span>
              </div>
              <div className="lane__body">
                {laneItems.length === 0 ? (
                  <p className="lane__empty muted">empty</p>
                ) : (
                  laneItems.map((item) => (
                    <WorkCard key={item.id} item={item} onTrace={openRun} />
                  ))
                )}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
