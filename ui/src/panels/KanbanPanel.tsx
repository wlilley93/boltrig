// US-WRK-03: a board of work items in status lanes. Each card shows intent,
// where it came from, confidence, owner and a handle to its run, with a trace
// action that pulls the audit execution tree.

import { api } from "../api/client";
import type { WorkItem, WorkStatus } from "../api/types";
import { navigate, openRun } from "../router";
import { useSlideActive } from "../deck/context";
import { useFetch } from "../useFetch";
import { EmptyState, FetchError, PageIntro, WORK_STATUS } from "./ux";

const LANES: ReadonlyArray<{ status: WorkStatus; label: string }> = [
  { status: "pending", label: "Pending" },
  { status: "in_flight", label: "In flight" },
  { status: "blocked", label: "Blocked" },
  { status: "awaiting_human", label: "Awaiting human" },
  { status: "done", label: "Done" },
  { status: "failed", label: "Failed" },
];

function confidenceText(c: WorkItem["confidence"]): string {
  if (c === null || c === undefined) return "unknown";
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
      <div className="card__intent">{item.intent || "(no description)"}</div>
      <dl className="card__meta">
        <div>
          <dt>Came from</dt>
          <dd>{item.source ?? "unknown"}</dd>
        </div>
        <div>
          <dt>Owner</dt>
          <dd>{item.owner_member ?? "unassigned"}</dd>
        </div>
        <div>
          <dt title="How sure the system is about this item.">
            <span className="ux-termtip">Confidence</span>
          </dt>
          <dd>{confidenceText(item.confidence)}</dd>
        </div>
        <div>
          <dt title="The system expects this to settle on a single answer.">
            <span className="ux-termtip">Convergent</span>
          </dt>
          <dd>{item.convergent ? "yes" : "no"}</dd>
        </div>
      </dl>
      <div className="card__foot">
        {item.hatchet_run_id ? (
          <button
            className="run-handle"
            title={`View run ${item.hatchet_run_id}`}
            onClick={() => onTrace(item.hatchet_run_id as string)}
          >
            View run -&gt;
          </button>
        ) : (
          <span className="muted">Not started yet</span>
        )}
      </div>
    </article>
  );
}

export function KanbanPanel() {
  // Quiesce the 10s board poll while this slide is not the active deck cell.
  const active = useSlideActive();
  const work = useFetch(() => api.work(), [], 10000, { paused: !active });

  const items = work.data?.items ?? [];
  const byStatus = new Map<WorkStatus, WorkItem[]>();
  for (const lane of LANES) byStatus.set(lane.status, []);
  for (const item of items) {
    const bucket = byStatus.get(item.status);
    if (bucket) bucket.push(item);
    else byStatus.set(item.status, [item]);
  }

  const empty = !work.loading && !work.error && items.length === 0;

  return (
    <section className="panel">
      <PageIntro
        title="Kanban"
        lead="A live board of every work item, grouped by where it is in its journey - from pending to done."
        how="Each card is one unit of work. Cards move left-to-right as the system makes progress; the board refreshes every 10 seconds."
        actions={
          <>
            <span className="muted">{items.length} item(s)</span>
            <button className="btn" onClick={() => work.reload()}>
              Refresh
            </button>
          </>
        }
      />

      {work.loading && !work.data && <p className="muted">Loading...</p>}
      <FetchError error={work.error} status={work.errorStatus} onRetry={work.reload} />

      {empty ? (
        <EmptyState
          title="No work yet"
          body="Work items appear here as conversations and workflows create them."
          action={
            <button className="btn btn--primary" onClick={() => navigate("/chat")}>
              Start in Chat
            </button>
          }
        />
      ) : (
        <div className="board">
          {LANES.map((lane) => {
            const laneItems = byStatus.get(lane.status) ?? [];
            return (
              <div className="lane" key={lane.status}>
                <div
                  className={`lane__head lane__head--${lane.status}`}
                  title={WORK_STATUS[lane.status]?.tip}
                >
                  <span className="ux-termtip">{lane.label}</span>
                  <span className="lane__count">{laneItems.length}</span>
                </div>
                <div className="lane__body">
                  {laneItems.length === 0 ? (
                    <p className="lane__empty muted">Nothing here</p>
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
      )}
    </section>
  );
}
