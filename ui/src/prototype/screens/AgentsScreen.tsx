import { agents, byId, workItems, workers } from "../model";
import { usePrototype } from "../PrototypeContext";
import { Icon } from "../PrototypeIcons";

function AgentNode({ id }: { id: string }) {
  const { select } = usePrototype();
  const agent = byId(agents, id);
  if (!agent) return null;
  const children = workers.filter((worker) => worker.parentAgent === agent.id);
  return <div className={`proto-org-node proto-org-node--t${agent.tier}`}>
    <button onClick={() => select({ kind: "agent", id: agent.id })}>
      <i>{agent.tier === 1 ? "ϟ" : agent.name[0]}</i>
      <span><strong>{agent.name}</strong><small>{agent.title}</small></span>
      <em className={`is-${agent.status}`} />
      <dl><div><dt>Work</dt><dd>{agent.activeWork}</dd></div><div><dt>Budget</dt><dd>{agent.budgetUsed}%</dd></div><div><dt>Heartbeat</dt><dd>{agent.nextHeartbeat}</dd></div></dl>
    </button>
    {children.length > 0 && <div className="proto-org-workers">{children.map((worker) => <button key={worker.id} onClick={() => select({ kind: "worker", id: worker.id })}><Icon name="spark" size={14} /><span>{worker.name.replace(/ T3-.*/, "")}<small>{worker.step}</small></span><b>{worker.cost}</b></button>)}</div>}
  </div>;
}

export function AgentsScreen() {
  const { select, notify } = usePrototype();
  const chief = agents.find((agent) => agent.tier === 1);
  const heads = agents.filter((agent) => agent.tier === 2);
  return (
    <section className="proto-page proto-agents">
      <header className="proto-page__header"><div><p className="proto-eyebrow">Organisation</p><h1>Agents</h1><p>Durable leaders own outcomes. Ephemeral workers appear only while bounded work is active.</p></div><div className="proto-header-actions"><button className="proto-button proto-button--secondary" onClick={() => notify("Roster view selected")}>Roster</button><button className="proto-button proto-button--primary" onClick={() => notify("Durable profile creator opened")}><Icon name="plus" size={16} />New agent</button></div></header>
      <div className="proto-org-summary"><span><strong>1</strong>Tier 1 chief</span><span><strong>3</strong>Tier 2 departments</span><span><strong>{workers.length}</strong>Tier 3 active</span><span><strong>{workItems.filter((work) => work.status === "in-flight").length}</strong>Runs in flight</span></div>
      <div className="proto-org-chart">
        <div className="proto-org-chart__chief">{chief && <AgentNode id={chief.id} />}</div>
        <div className="proto-org-line" />
        <div className="proto-org-chart__heads">{heads.map((agent) => <AgentNode key={agent.id} id={agent.id} />)}</div>
      </div>
      <div className="proto-agent-legend"><span><i className="proto-legend-t1" />Tier 1 durable chief</span><span><i className="proto-legend-t2" />Tier 2 durable department</span><span><i className="proto-legend-t3" />Tier 3 ephemeral worker</span><button onClick={() => select({ kind: "worker", id: "worker-a19f" })}>Inspect a live worker →</button></div>
    </section>
  );
}
