import { agents, byId, runs, workItems } from "../model";
import { usePrototype } from "../PrototypeContext";
import { Icon } from "../PrototypeIcons";

export function RunsApprovalsScreen({ mode }: { mode: "runs" | "approvals" }) {
  const { approvals, select } = usePrototype();
  return <section className="proto-page">
    <header className="proto-page__header"><div><p className="proto-eyebrow">{mode === "runs" ? "Execution" : "Human control"}</p><h1>{mode === "runs" ? "Runs" : "Approvals"}</h1><p>{mode === "runs" ? "Follow durable execution, worker lineage, cost, and intervention state." : "Make explicit decisions with the actor, stakes, parameters, and run context visible."}</p></div></header>
    {mode === "runs" ? <div className="proto-table proto-runs-table"><div className="proto-table__head"><span>State</span><span>Run</span><span>Owner</span><span>Cost</span><span>Duration</span></div>{runs.map((run) => <button className="proto-table__row" key={run.id} onClick={() => select({ kind: "run", id: run.id })}><span><i className={`proto-status-dot is-${run.status}`} />{run.status}</span><span><strong>{run.title}</strong><small>{run.id} · {byId(workItems, run.workId)?.title}</small></span><span>{byId(agents, run.agentId)?.name}</span><span>{run.cost}</span><span>{run.duration}</span></button>)}</div> : <div className="proto-approval-list">{approvals.map((approval) => <button key={approval.id} aria-label={`Review approval: ${approval.title}`} className={`proto-approval-card is-${approval.status}`} onClick={() => select({ kind: "approval", id: approval.id })}><span className="proto-approval-card__icon"><Icon name={approval.status === "approved" ? "check" : "approval"} /></span><span><small>{approval.consequence} consequence · {approval.verb}</small><strong>{approval.title}</strong><p>{approval.stakes}</p><em>{byId(agents, approval.requestedBy)?.name} · {approval.runId}</em></span><b>{approval.status === "pending" ? "Review" : approval.status}</b></button>)}</div>}
  </section>;
}
