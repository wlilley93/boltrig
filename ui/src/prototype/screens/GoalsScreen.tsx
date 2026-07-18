import { useState } from "react";

import { agents, byId, projects, type Goal, workItems } from "../model";
import { usePrototype } from "../PrototypeContext";
import { Icon } from "../PrototypeIcons";

export function GoalsScreen() {
  const { goals, addGoal, select } = usePrototype();
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!title.trim()) return;
    const goal: Goal = { id: `goal-${Date.now()}`, title: title.trim(), outcome: "Define a measurable outcome for this goal.", status: "on-track", progress: 0, owner: "agent-bolt", target: "31 Dec 2026", budget: "£2,000", spent: "£0" };
    addGoal(goal);
    setTitle("");
    setCreating(false);
  };

  return (
    <section className="proto-page">
      <header className="proto-page__header"><div><p className="proto-eyebrow">Direction</p><h1>Goals and projects</h1><p>Connect mission to measurable outcomes, accountable owners, and executable work.</p></div><button className="proto-button proto-button--primary" onClick={() => setCreating(true)}><Icon name="plus" size={16} />New goal</button></header>
      <div className="proto-goal-board">
        <div className="proto-goal-board__head"><span>Outcome</span><span>Owner</span><span>Progress</span><span>Target</span></div>
        {goals.map((goal) => {
          const linkedProjects = projects.filter((project) => project.goalId === goal.id);
          return <article className="proto-goal-card" key={goal.id}>
            <button className="proto-goal-card__main" onClick={() => select({ kind: "goal", id: goal.id })}>
              <span><i className={`proto-status-dot is-${goal.status}`} /><strong>{goal.title}</strong><small>{goal.outcome}</small></span><b>{byId(agents, goal.owner)?.name}</b><span className="proto-goal-percent"><i><em style={{ width: `${goal.progress}%` }} /></i><b>{goal.progress}%</b></span><b>{goal.target}</b>
            </button>
            {linkedProjects.length > 0 && <div className="proto-projects">{linkedProjects.map((project) => <button key={project.id} onClick={() => select({ kind: "project", id: project.id })}><span>{project.title}<small>{workItems.filter((work) => work.projectId === project.id).length} work items</small></span><b>{project.confidence}% confidence</b><em className={`is-${project.status}`}>{project.status}</em></button>)}</div>}
          </article>;
        })}
      </div>
      {creating && <div className="proto-modal-backdrop" role="presentation"><form className="proto-modal" onSubmit={submit}><p className="proto-eyebrow">New direction</p><h2>Create a goal</h2><label className="proto-field">Outcome title<input autoFocus value={title} onChange={(event) => setTitle(event.target.value)} placeholder="What should change?" /></label><label className="proto-field">Owner<select defaultValue="agent-bolt">{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name} — {agent.title}</option>)}</select></label><div className="proto-form-grid"><label className="proto-field">Target date<input type="date" defaultValue="2026-12-31" /></label><label className="proto-field">Budget<input defaultValue="£2,000" /></label></div><div className="proto-modal__actions"><button type="button" className="proto-button proto-button--secondary" onClick={() => setCreating(false)}>Cancel</button><button className="proto-button proto-button--primary" disabled={!title.trim()}>Create goal</button></div></form></div>}
    </section>
  );
}
