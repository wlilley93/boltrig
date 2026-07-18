import { type KeyboardEvent, useEffect, useId, useRef, useState } from "react";

import { agents, byId, conversations, goals, projects, runs, workItems, workers } from "./model";
import { usePrototype } from "./PrototypeContext";
import { Icon } from "./PrototypeIcons";

function Fact({ label, value }: { label: string; value: string | number }) {
  return <div className="proto-fact"><span>{label}</span><strong>{value}</strong></div>;
}

export function EntityInspector() {
  const { selection, select, goals: liveGoals, approvals: liveApprovals, closeInspector, decideApproval, notify, stoppedRunIds, stopRun } = usePrototype();
  const [pendingDecision, setPendingDecision] = useState<{ id: string; status: "approved" | "rejected" } | null>(null);
  const inspectorRef = useRef<HTMLElement>(null);
  const titleId = useId();
  const mobile = window.innerWidth <= 760;
  const goal = selection.kind === "goal" ? byId(liveGoals, selection.id) : undefined;
  const project = selection.kind === "project" ? byId(projects, selection.id) : undefined;
  const work = selection.kind === "work" ? byId(workItems, selection.id) : undefined;
  const agent = selection.kind === "agent" ? byId(agents, selection.id) : undefined;
  const worker = selection.kind === "worker" ? byId(workers, selection.id) : undefined;
  const run = selection.kind === "run" ? byId(runs, selection.id) : undefined;
  const approval = selection.kind === "approval" ? byId(liveApprovals, selection.id) : undefined;
  const automation = selection.kind === "automation";
  const conversation = selection.kind === "conversation" ? byId(conversations, selection.id) : undefined;
  const runStopped = run ? stoppedRunIds.includes(run.id) : false;
  const workerStopped = worker ? stoppedRunIds.includes(worker.runId) : false;
  const title = conversation?.title ?? goal?.title ?? project?.title ?? work?.title ?? agent?.name ?? worker?.name ?? run?.title ?? approval?.title ?? (automation ? "Weekly customer evidence digest" : selection.kind === "node" ? selection.id : "Selection");
  const kicker = conversation ? "Conversation" : goal ? "Goal" : project ? "Project" : work ? "Work item" : agent ? `Tier ${agent.tier} durable agent` : worker ? "Tier 3 ephemeral worker" : run ? "Run" : approval ? "Approval" : automation ? "Automation" : "Automation node";

  useEffect(() => setPendingDecision(null), [selection.kind, selection.id]);

  const containFocus = (event: KeyboardEvent<HTMLElement>) => {
    if (!mobile) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeInspector();
      return;
    }
    if (event.key !== "Tab") return;
    const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')).filter((element) => element.offsetParent !== null);
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (!first || !last) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <aside ref={inspectorRef} className="proto-inspector" role={mobile ? "dialog" : undefined} aria-modal={mobile || undefined} aria-label={mobile ? undefined : "Context inspector"} aria-labelledby={mobile ? titleId : undefined} onKeyDown={containFocus}>
      <header><div><p className="proto-eyebrow">{kicker}</p><h2 id={titleId}>{title}</h2></div><div className="proto-inspector__header-actions"><button type="button" className="proto-icon-button" onClick={() => notify("Deep link copied")} aria-label="Copy deep link">↗</button><button type="button" className="proto-icon-button proto-inspector-close" autoFocus={mobile} onClick={closeInspector} aria-label="Close inspector">×</button></div></header>
      <div className="proto-inspector__body">
        {conversation && <><p className="proto-inspector__lead">An auditable launch surface for governed work, specialist workers and reusable workflows.</p><Fact label="Actor" value="Bolt · Chief of Staff" /><Fact label="State" value={conversation.state} /><Fact label="Updated" value={conversation.updated} /><Fact label="Workspace" value="Boltrig Labs" />{conversation.runId && <button type="button" className="proto-button proto-button--secondary" onClick={() => select({ kind: "run", id: conversation.runId! })}><Icon name="run" size={15} />Inspect connected run</button>}<div className="proto-section"><h3>Available context</h3><div className="proto-chips"><span>Goals</span><span>Work</span><span>Agents</span><span>Memory</span><span>Workflows</span></div></div></>}
        {goal && <>
          <p className="proto-inspector__lead">{goal.outcome}</p>
          <div className="proto-progress"><i style={{ width: `${goal.progress}%` }} /><span>{goal.progress}%</span></div>
          <Fact label="State" value={goal.status.replace("-", " ")} /><Fact label="Owner" value={byId(agents, goal.owner)?.name ?? goal.owner} /><Fact label="Target" value={goal.target} /><Fact label="Budget" value={`${goal.spent} of ${goal.budget}`} />
          <div className="proto-section"><h3>Linked projects</h3>{projects.filter((p) => p.goalId === goal.id).map((p) => <button className="proto-link-row" key={p.id}>{p.title}<span>{p.confidence}%</span></button>)}</div>
        </>}
        {project && <><p className="proto-inspector__lead">A bounded programme of aligned work.</p><Fact label="State" value={project.status} /><Fact label="Confidence" value={`${project.confidence}%`} /><Fact label="Owner" value={byId(agents, project.owner)?.name ?? project.owner} /><Fact label="Goal" value={byId(goals, project.goalId)?.title ?? project.goalId} /></>}
        {work && <><div className={`proto-state proto-state--${work.status}`}>{work.status.replace("-", " ")}</div><Fact label="Priority" value={work.priority} /><Fact label="Durable owner" value={byId(agents, work.owner)?.name ?? work.owner} /><Fact label="Current worker" value={work.worker ? byId(workers, work.worker)?.name ?? work.worker : "Not spawned"} /><Fact label="Due" value={work.due} /><Fact label="Alignment" value={work.aligned ? "Goal aligned" : "Ad-hoc"} />{work.dependency && <div className="proto-callout proto-callout--warn"><Icon name="warning" size={16} /><span><b>Blocked</b>{work.dependency}</span></div>}{work.artifact && <div className="proto-section"><h3>Latest output</h3><button className="proto-artifact">▱ {work.artifact}</button></div>}</>}
        {agent && <><div className={`proto-agent-sigil proto-agent-sigil--t${agent.tier}`}>{agent.tier === 1 ? "ϟ" : agent.name.slice(0, 1)}</div><p className="proto-inspector__lead">{agent.title} · {agent.department}</p><Fact label="Status" value={agent.status} /><Fact label="Active work" value={agent.activeWork} /><Fact label="Budget used" value={`${agent.budgetUsed}%`} /><Fact label="Next heartbeat" value={agent.nextHeartbeat} /><div className="proto-section"><h3>Effective capabilities</h3><div className="proto-chips">{agent.capabilities.map((cap) => <span key={cap}>{cap}</span>)}</div></div><button className="proto-button proto-button--secondary" onClick={() => notify(agent.status === "paused" ? "Agent resumed" : "Future heartbeats paused")}><Icon name={agent.status === "paused" ? "play" : "pause"} size={15} />{agent.status === "paused" ? "Resume agent" : "Pause future work"}</button></>}
        {worker && <><div className="proto-worker-sigil"><Icon name="spark" /></div><p className="proto-inspector__lead">{worker.purpose}</p><Fact label="Parent" value={byId(agents, worker.parentAgent)?.name ?? worker.parentAgent} /><Fact label="State" value={workerStopped ? "stopped" : worker.status} /><Fact label="Current step" value={workerStopped ? "Stopped at the run checkpoint" : worker.step} /><Fact label="Age" value={worker.age} /><Fact label="Expiry" value={worker.expires} /><Fact label="Cost" value={worker.cost} /><div className="proto-section"><h3>Effective grants</h3><div className="proto-chips">{worker.grants.map((grant) => <span key={grant}>{grant}</span>)}</div></div></>}
        {run && <><div className={`proto-state proto-state--${runStopped ? "stopped" : run.status}`}>{runStopped ? "stopped" : run.status}</div><Fact label="Run ID" value={run.id} /><Fact label="Cost" value={run.cost} /><Fact label="Duration" value={run.duration} /><div className="proto-timeline">{run.steps.map((step) => { const stepStatus = runStopped && step.status === "running" ? "stopped" : step.status; return <div key={step.label} className={`proto-timeline__step is-${stepStatus}`}><i /><span>{step.label}</span><small>{stepStatus}</small></div>; })}</div><div className="proto-action-row"><button type="button" className="proto-button proto-button--secondary" disabled={runStopped} onClick={() => stopRun(run.id)}><Icon name="pause" size={15} />{runStopped ? "Run stopped" : "Stop run"}</button><button type="button" className="proto-button proto-button--secondary" onClick={() => notify("Run fork created")}>Fork</button></div></>}
        {approval && <><div className="proto-callout proto-callout--warn"><Icon name="warning" /><span><b>{approval.consequence} consequence</b>{approval.stakes}</span></div><Fact label="Requested by" value={byId(agents, approval.requestedBy)?.name ?? approval.requestedBy} /><Fact label="Verb" value={approval.verb} /><Fact label="Run" value={approval.runId} /><Fact label="State" value={approval.status} />{approval.status === "pending" && pendingDecision?.id !== approval.id && <div className="proto-approval-actions"><button type="button" className="proto-button proto-button--primary" onClick={() => setPendingDecision({ id: approval.id, status: "approved" })}>Approve intentionally</button><button type="button" className="proto-button proto-button--secondary" onClick={() => setPendingDecision({ id: approval.id, status: "rejected" })}>Reject</button></div>}{approval.status === "pending" && pendingDecision?.id === approval.id && <div className="proto-inspector-confirm" role="group" aria-label={`Confirm ${pendingDecision.status === "approved" ? "approval" : "rejection"} for ${approval.title}`} aria-live="polite"><p>Confirm <b>{pendingDecision.status === "approved" ? "approval" : "rejection"}</b> of <code>{approval.verb}</code> for this run?</p><div><button type="button" className="proto-button proto-button--secondary" onClick={() => setPendingDecision(null)}>Cancel</button><button type="button" className="proto-button proto-button--primary" onClick={() => { decideApproval(approval.id, pendingDecision.status); setPendingDecision(null); }}>Confirm {pendingDecision.status === "approved" ? "approval" : "rejection"}</button></div></div>}</>}
        {automation && <><p className="proto-inspector__lead">A governed workflow with typed steps, explicit consequence, and a publishable revision history.</p><Fact label="State" value="Draft" /><Fact label="Revision" value="v8" /><Fact label="Schedule" value="Mondays · 09:00" /><Fact label="Owner" value="Product" /><div className="proto-section"><h3>Controls</h3><div className="proto-chips"><span>Versioned</span><span>Human gate</span><span>Replayable</span></div></div></>}
        {selection.kind === "node" && <><p className="proto-inspector__lead">Configure this typed automation step and test it with pinned data.</p><label className="proto-field">Operation<select defaultValue="summarize"><option value="summarize">Summarize evidence</option><option value="classify">Classify evidence</option></select></label><label className="proto-field">Input expression<input defaultValue="{{ merge.findings }}" /></label><div className="proto-section"><h3>Policy</h3><Fact label="Timeout" value="5 minutes" /><Fact label="Retries" value="2 with backoff" /><Fact label="Consequence" value="Low" /></div><button className="proto-button proto-button--secondary" onClick={() => notify("Node test completed with 12 evidence items")}>Test this node</button></>}
      </div>
    </aside>
  );
}
