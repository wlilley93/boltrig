import { useState } from "react";

import { agents, byId, goals, projects, type Selection, workItems, workers } from "../model";
import { usePrototype } from "../PrototypeContext";
import { Icon } from "../PrototypeIcons";

const statuses = ["pending", "in-flight", "blocked", "awaiting-human"] as const;
type WorkMode = "list" | "board" | "hierarchy";
type SelectEntity = (selection: Selection) => void;

function WorkToolbar({ mode, setMode }: { mode: WorkMode; setMode: (mode: WorkMode) => void }) {
  return (
    <div className="proto-toolbar">
      <div className="proto-segmented" role="group" aria-label="Work view">
        {(["list", "board", "hierarchy"] as const).map((name) => (
          <button type="button" key={name} aria-pressed={mode === name} className={mode === name ? "is-active" : ""} onClick={() => setMode(name)}>{name}</button>
        ))}
      </div>
      <div className="proto-filter-chips" aria-label="Current work filters">
        <span>All owners</span><span>All goals</span><span>Active + blocked</span>
      </div>
    </div>
  );
}

function WorkList({ select }: { select: SelectEntity }) {
  return (
    <div className="proto-table" role="region" aria-label="Work item list" tabIndex={0}>
      <div className="proto-table__head" aria-hidden="true"><span>Status</span><span>Work</span><span>Lineage</span><span>Owner</span><span>Due</span></div>
      {workItems.map((work) => (
        <button type="button" className="proto-table__row" key={work.id} onClick={() => select({ kind: "work", id: work.id })}>
          <span><i className={`proto-status-dot is-${work.status}`} />{work.status.replace("-", " ")}</span>
          <span><strong>{work.title}</strong><small>{work.worker ? byId(workers, work.worker)?.name : work.aligned ? "No active worker" : "Ad-hoc work"}</small></span>
          <span>{work.projectId ? byId(projects, work.projectId)?.title : "Unaligned"}<small>{work.goalId ? byId(goals, work.goalId)?.title : "No goal"}</small></span>
          <span>{byId(agents, work.owner)?.name}<small>{work.priority} priority</small></span>
          <span>{work.due}</span>
        </button>
      ))}
    </div>
  );
}

function WorkBoard({ select }: { select: SelectEntity }) {
  return (
    <div className="proto-board">
      {statuses.map((status) => (
        <section className="proto-board__column" key={status} aria-label={`${status.replace("-", " ")} work`}>
          <header><span>{status.replace("-", " ")}</span><b>{workItems.filter((work) => work.status === status).length}</b></header>
          {workItems.filter((work) => work.status === status).map((work) => (
            <button type="button" key={work.id} onClick={() => select({ kind: "work", id: work.id })}>
              <strong>{work.title}</strong><span>{byId(agents, work.owner)?.name}</span><small>{work.goalId ? byId(goals, work.goalId)?.title : "Ad-hoc"}</small>
              {work.worker && <em><Icon name="spark" size={12} />Tier 3 active</em>}
            </button>
          ))}
        </section>
      ))}
    </div>
  );
}

function WorkHierarchy({ select }: { select: SelectEntity }) {
  return (
    <div className="proto-hierarchy">
      {goals.map((goal) => (
        <article key={goal.id}>
          <button type="button" onClick={() => select({ kind: "goal", id: goal.id })}><Icon name="goal" /><span>{goal.title}<small>{goal.progress}% complete</small></span></button>
          {projects.filter((project) => project.goalId === goal.id).map((project) => (
            <div key={project.id}>
              <button type="button" onClick={() => select({ kind: "project", id: project.id })}><span>{project.title}<small>{project.confidence}% confidence</small></span></button>
              {workItems.filter((work) => work.projectId === project.id).map((work) => (
                <button type="button" key={work.id} onClick={() => select({ kind: "work", id: work.id })}><i className={`proto-status-dot is-${work.status}`} /><span>{work.title}<small>{byId(agents, work.owner)?.name}</small></span></button>
              ))}
            </div>
          ))}
        </article>
      ))}
    </div>
  );
}

export function WorkScreen() {
  const { select, notify } = usePrototype();
  const [mode, setMode] = useState<WorkMode>("list");
  return (
    <section className="proto-page proto-work">
      <header className="proto-page__header">
        <div><p className="proto-eyebrow">Execution</p><h1>Work</h1><p>Track aligned outcomes, durable ownership, and the workers currently doing the job.</p></div>
        <button type="button" className="proto-button proto-button--primary" onClick={() => notify("Work command sheet opened")}><Icon name="plus" size={16} />New work</button>
      </header>
      <WorkToolbar mode={mode} setMode={setMode} />
      {mode === "list" && <WorkList select={select} />}
      {mode === "board" && <WorkBoard select={select} />}
      {mode === "hierarchy" && <WorkHierarchy select={select} />}
    </section>
  );
}
