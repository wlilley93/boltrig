import { useState } from "react";
import type { CSSProperties } from "react";

import type { WorkItem, WorkStatus } from "@/api/types";
import { navigate } from "@/router";
import { RunLink } from "@/panels/shared";
import { StatusBadge, WORK_STATUS } from "@/panels/ux";
import {
  WORK_STATUS_ORDER,
  buildWorkForest,
  childCounts,
  linearWorkItems,
  type WorkTreeNode,
  type WorkView,
} from "./model";

const LANE_LABELS: Record<WorkStatus, string> = {
  pending: "Pending",
  in_flight: "In flight",
  blocked: "Blocked",
  awaiting_human: "Awaiting human",
  done: "Done",
  failed: "Failed",
};

function WorkCard({ item, childCount = 0 }: { item: WorkItem; childCount?: number }) {
  return (
    <article className={`work-card ${item.convergent ? "work-card--goal" : ""}`}>
      <button className="work-card__main" onClick={() => navigate(`/kanban/${item.id}`)}>
        <span className="work-card__intent">{item.intent || "(no description)"}</span>
        <span className="work-card__id">{item.id}</span>
      </button>
      <div className="work-card__meta">
        <span>{item.owner_member || "Unassigned"}</span>
        <span>{item.source || "Unknown source"}</span>
        {item.parent_id && <span>Child of {item.parent_id}</span>}
        {childCount > 0 && <span>{childCount} child{childCount === 1 ? "" : "ren"}</span>}
        {item.convergent && <span className="work-card__goal">Convergent goal</span>}
      </div>
      <div className="work-card__foot">
        <StatusBadge value={item.status} glossary={WORK_STATUS} />
        {item.hatchet_run_id ? <RunLink runId={item.hatchet_run_id} /> : <span className="muted">No run</span>}
      </div>
    </article>
  );
}

function BoardView({ items }: { items: WorkItem[] }) {
  const counts = childCounts(items);
  return (
    <div className="board work-board" aria-label="Board view">
      {WORK_STATUS_ORDER.map((status) => {
        const laneItems = items.filter((item) => item.status === status);
        return (
          <section className="lane" key={status}>
            <div className={`lane__head lane__head--${status}`}>
              <span>{LANE_LABELS[status]}</span>
              <span className="lane__count">{laneItems.length}</span>
            </div>
            <div className="lane__body">
              {laneItems.length
                ? laneItems.map((item) => <WorkCard key={item.id} item={item} childCount={counts.get(item.id)} />)
                : <p className="lane__empty muted">Nothing here</p>}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function ProjectNode({ node, depth = 0 }: { node: WorkTreeNode; depth?: number }) {
  const [open, setOpen] = useState(true);
  const hasChildren = node.children.length > 0;
  return (
    <li className="work-tree__item">
      <div className="work-tree__row" style={{ "--work-depth": depth } as CSSProperties}>
        {hasChildren ? (
          <button
            className="work-tree__toggle"
            aria-label={`${open ? "Collapse" : "Expand"} ${node.item.intent}`}
            aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
          >
            {open ? "−" : "+"}
          </button>
        ) : <span className="work-tree__toggle work-tree__toggle--blank" />}
        <button className="work-tree__link" onClick={() => navigate(`/kanban/${node.item.id}`)}>
          <span>{node.item.intent || "(no description)"}</span>
          <code>{node.item.id}</code>
        </button>
        {node.item.convergent && <span className="work-card__goal">Goal</span>}
        <StatusBadge value={node.item.status} glossary={WORK_STATUS} />
        {hasChildren && <span className="muted">{node.children.length} child{node.children.length === 1 ? "" : "ren"}</span>}
      </div>
      {hasChildren && open && (
        <ul className="work-tree">
          {node.children.map((child) => <ProjectNode key={child.item.id} node={child} depth={depth + 1} />)}
        </ul>
      )}
    </li>
  );
}

function ProjectView({ items }: { items: WorkItem[] }) {
  const roots = buildWorkForest(items);
  return (
    <section className="work-project" aria-label="Project view">
      <ul className="work-tree">
        {roots.map((node) => <ProjectNode key={node.item.id} node={node} />)}
      </ul>
    </section>
  );
}

function LinearView({ items }: { items: WorkItem[] }) {
  return (
    <div className="table-scroll" aria-label="Linear view">
      <table className="data-table work-linear">
        <thead><tr><th>Work</th><th>Status</th><th>Owner</th><th>Source</th><th>Parent</th><th>Run</th></tr></thead>
        <tbody>
          {linearWorkItems(items).map((item) => (
            <tr key={item.id}>
              <td><button className="entity-link" onClick={() => navigate(`/kanban/${item.id}`)}>{item.intent || item.id}</button></td>
              <td><StatusBadge value={item.status} glossary={WORK_STATUS} /></td>
              <td>{item.owner_member || <span className="muted">Unassigned</span>}</td>
              <td>{item.source || <span className="muted">Unknown</span>}</td>
              <td>{item.parent_id ? <button className="entity-link" onClick={() => navigate(`/kanban/${item.parent_id}`)}>{item.parent_id}</button> : <span className="muted">Root</span>}</td>
              <td>{item.hatchet_run_id ? <RunLink runId={item.hatchet_run_id} /> : <span className="muted">No run</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function WorkViews({ view, items }: { view: WorkView; items: WorkItem[] }) {
  if (view === "project") return <ProjectView items={items} />;
  if (view === "linear") return <LinearView items={items} />;
  return <BoardView items={items} />;
}
