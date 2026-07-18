import { agents, byId, runs, workItems, workers } from "../model";
import { usePrototype } from "../PrototypeContext";
import { Icon } from "../PrototypeIcons";

export function HomeScreen() {
  const { goals, approvals: liveApprovals, select, notify } = usePrototype();
  const pending = liveApprovals.filter((approval) => approval.status === "pending");
  return (
    <section className="proto-page proto-home">
      <header className="proto-page__header">
        <div><p className="proto-eyebrow">Wednesday, 15 July</p><h1>Good morning, Will.</h1><p>The organisation is moving. Three things need your attention.</p></div>
        <div className="proto-header-actions"><span className="proto-env"><i />Development</span><button className="proto-button proto-button--primary" onClick={() => notify("Command sheet opened — try ⌘K in production")}>Ask Bolt</button></div>
      </header>

      <div className="proto-briefing">
        <div><span>Active work</span><strong>13</strong><small>3 ephemeral workers</small></div>
        <div><span>Needs you</span><strong>{pending.length + 1}</strong><small>2 approvals · 1 blocker</small></div>
        <div><span>Monthly spend</span><strong>£4,920</strong><small>61% of £8,000</small></div>
        <div><span>Runtime posture</span><strong className="proto-text-warn">Degraded</strong><small>Operations heartbeat held</small></div>
      </div>

      <div className="proto-home__grid">
        <article className="proto-panel proto-panel--goals">
          <div className="proto-panel__title"><div><p className="proto-eyebrow">Direction</p><h2>Goals</h2></div><a href="#/prototype/goals">View all</a></div>
          {goals.map((goal) => <button className="proto-goal-row" key={goal.id} onClick={() => select({ kind: "goal", id: goal.id })}>
            <span className={`proto-status-dot is-${goal.status}`} /><span className="proto-goal-row__title">{goal.title}<small>{byId(agents, goal.owner)?.name} · {goal.target}</small></span><span className="proto-mini-progress"><i style={{ width: `${goal.progress}%` }} /></span><strong>{goal.progress}%</strong>
          </button>)}
        </article>

        <article className="proto-panel proto-panel--attention">
          <div className="proto-panel__title"><div><p className="proto-eyebrow">Intervention</p><h2>Needs you</h2></div><span>{pending.length + 1}</span></div>
          {pending.map((approval) => <button className="proto-attention-row" key={approval.id} onClick={() => select({ kind: "approval", id: approval.id })}><Icon name="approval" /><span>{approval.title}<small>{byId(agents, approval.requestedBy)?.name} · {approval.consequence} consequence</small></span><b>Review</b></button>)}
          <button className="proto-attention-row" onClick={() => select({ kind: "work", id: "work-143" })}><Icon name="warning" /><span>Restore drill is blocked<small>Operations · due 18 Jul</small></span><b>Open</b></button>
        </article>

        <article className="proto-panel proto-panel--agents">
          <div className="proto-panel__title"><div><p className="proto-eyebrow">Organisation</p><h2>Agents at work</h2></div><a href="#/prototype/agents">Open org</a></div>
          <div className="proto-agent-strip">
            {agents.map((agent) => <button key={agent.id} className={`proto-agent-token proto-agent-token--t${agent.tier}`} onClick={() => select({ kind: "agent", id: agent.id })}><i>{agent.tier === 1 ? "ϟ" : agent.name[0]}</i><span>{agent.name}<small>{agent.activeWork} active</small></span><em className={`is-${agent.status}`} /></button>)}
          </div>
          <div className="proto-worker-list"><span>Ephemeral workers</span>{workers.map((worker) => <button key={worker.id} onClick={() => select({ kind: "worker", id: worker.id })}><Icon name="spark" size={14} /><span>{worker.name}<small>{worker.step}</small></span><b>{worker.cost}</b></button>)}</div>
        </article>

        <article className="proto-panel proto-panel--activity">
          <div className="proto-panel__title"><div><p className="proto-eyebrow">Live</p><h2>Work in flight</h2></div><a href="#/prototype/runs">All runs</a></div>
          {runs.slice(0, 2).map((run) => <button className="proto-run-row" key={run.id} onClick={() => select({ kind: "run", id: run.id })}><span className={`proto-run-state is-${run.status}`}><Icon name={run.status === "running" ? "play" : "pause"} size={13} /></span><span>{run.title}<small>{byId(workItems, run.workId)?.title}</small></span><b>{run.cost}</b><em>{run.duration}</em></button>)}
        </article>
      </div>
    </section>
  );
}
