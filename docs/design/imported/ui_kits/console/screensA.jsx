const { Node, RegistryNode, Badge, Button, Tag, ReasoningBlock, ToolCard, SubagentCard, ApprovalCard } = window.BoltrigDesignSystem_9308d4;
const D = window.KIT_DATA;

// ---- Home ------------------------------------------------------------------
function HomeScreen({ go, openRun }) {
  return (
    <section className="kit-panel">
      <div className="kit-panel__head">
        <div>
          <h2>Home</h2>
          <p className="sub" style={{margin:"6px 0 0"}}>{D.identity.subject} @ {D.identity.tenant} &mdash; {new Date().toLocaleDateString("en-GB",{weekday:"long",day:"numeric",month:"long"})}</p>
        </div>
        <div className="kit-actions">
          <Button variant="primary" onClick={() => go("chat")}>New conversation</Button>
          <Button onClick={() => go("studio")}>New workflow</Button>
        </div>
      </div>

      {/* Needs you - full width alert strip when pending */}
      <div style={{ borderLeft: "3px solid var(--color-consequence-high)", background: "rgba(255,122,69,0.07)", border: "1px solid rgba(255,122,69,0.3)", padding: "14px 18px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <Badge family="consequence" value="high" label="needs you" />
          <span style={{ fontSize: "var(--fs-sm)", color: "var(--color-text-primary)" }}>
            <strong>3 approvals</strong> are waiting - one is high consequence and paused a live run.
          </span>
        </div>
        <Button variant="danger" size="sm" onClick={() => go("approvals")}>Review approvals</Button>
      </div>

      <div className="kit-cols" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))" }}>
        {/* Recent runs */}
        <div className="bds-card">
          <div className="bds-card__head"><h3>Recent runs</h3><Button size="sm" variant="ghost">Refresh</Button></div>
          <div className="bds-card__body">
            {D.recentRuns.map((run) => (
              <div className="kit-row" key={run.runId}>
                <span className="kit-line-text" style={{ fontSize: "var(--fs-sm)" }}>{run.intent}</span>
                <span className="kit-kv">
                  <Badge family="run" value={run.status} label={run.status} />
                  <button className="kit-link" onClick={() => openRun(run.runId)}>open</button>
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Work summary */}
        <div className="bds-card">
          <div className="bds-card__head"><h3>Work in flight</h3><span className="kit-muted" style={{fontSize:11}}>7 items</span></div>
          <div className="bds-card__body">
            <div className="kit-metrics">
              <div className="kit-metric is-flight"><b>2</b><span>In flight</span></div>
              <div className="kit-metric"><b>1</b><span>Pending</span></div>
              <div className="kit-metric"><b>1</b><span>Blocked</span></div>
              <div className="kit-metric is-human"><b>1</b><span>Awaiting human</span></div>
              <div className="kit-metric"><b>1</b><span>Done</span></div>
              <div className="kit-metric"><b>1</b><span>Failed</span></div>
            </div>
            <div><Button variant="ghost" size="sm" onClick={() => go("kanban")}>Open board</Button></div>
          </div>
        </div>

        {/* Capabilities */}
        <div className="bds-card">
          <div className="bds-card__head"><h3>Capability scope</h3><span className="kit-muted" style={{fontSize:11}}>9 verbs</span></div>
          <div className="bds-card__body">
            <p className="kit-muted" style={{ margin: 0, fontSize: "var(--fs-sm)" }}>Scoped to 9 verbs across 4 nouns.</p>
            <div className="kit-kv">{D.capabilities.map((c) => <Tag key={c.noun}>{c.noun} ({c.verbs.length})</Tag>)}</div>
            <div><Button variant="ghost" size="sm" onClick={() => go("router")}>Browse router</Button></div>
          </div>
        </div>
      </div>
    </section>
  );
}

// ---- Approvals inbox -------------------------------------------------------
function ApprovalsScreen({ openRun }) {
  const [decided, setDecided] = React.useState({});
  const [notes, setNotes] = React.useState({});
  const pending = D.approvals.filter((a) => !decided[a.id]);
  return (
    <section className="kit-panel">
      <div className="kit-panel__head">
        <div>
          <h2>Approvals</h2>
          <p className="sub" style={{margin:"6px 0 0"}}>Every decision is full-context and deliberate - high-consequence first.</p>
        </div>
        <div className="kit-actions">
          <span className="kit-muted" style={{ fontSize: "var(--fs-sm)" }}>{pending.length} pending</span>
          <Button size="sm">Refresh</Button>
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 20, maxWidth: 720 }}>
        {D.approvals.map((a) => (
          <div key={a.id} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <ApprovalCard
              requestId={a.id} actor={a.actor} verb={a.verb}
              consequence={a.type === "escalation" ? "high" : a.type === "approval" ? "high" : "low"}
              inputs={a.inputs} reason={a.reason}
              state={decided[a.id] || "pending"}
              notes={notes[a.id] || ""}
              onNotesChange={(v) => setNotes((p) => ({ ...p, [a.id]: v }))}
              onApprove={() => setDecided((p) => ({ ...p, [a.id]: "approved" }))}
              onReject={() => setDecided((p) => ({ ...p, [a.id]: "rejected" }))}
            />
            {a.runId && (
              <div className="kit-kv" style={{ paddingLeft: 2 }}>
                <span className="kit-muted" style={{ fontSize: "var(--fs-xs)" }}>traces to</span>
                <button className="kit-link" onClick={() => openRun(a.runId)}>run: <code>{a.runId}</code></button>
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

// ---- Run drawer ------------------------------------------------------------
function TreeNode({ node }) {
  const statuses = Object.entries(node.statuses || {}).map(([s, n]) => `${s}:${n}`).join(" ");
  return (
    <li className="kit-tree__node">
      <div className="kit-tree__line">
        <code className="kit-mono" style={{ fontSize: 11, color: "var(--color-accent)" }}>{node.runId}</code>
        {node.actor && <span className="kit-muted" style={{ fontSize: 11 }}>{node.actor}</span>}
        {node.tier && <Badge family="role" label={node.tier} />}
        {statuses && <span className="kit-muted" style={{ fontSize: 11 }}>[{statuses}]</span>}
        <span className="kit-muted" style={{ fontSize: 11 }}>cost: {node.cost}u</span>
      </div>
      {node.children && node.children.length > 0 && (
        <ul className="kit-tree">{node.children.map((c) => <TreeNode key={c.runId} node={c} />)}</ul>
      )}
    </li>
  );
}

function RunDrawer({ runId, openRun, close }) {
  const t = D.runTree;
  const [notes, setNotes] = React.useState("");
  const [decided, setDecided] = React.useState(null);
  return (
    <div className="kit-overlay" onClick={close}>
      <div className="kit-drawer" onClick={(e) => e.stopPropagation()}>
        <div className="kit-drawer__head">
          <div>
            <h3>Run drawer</h3>
            <code style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--color-accent)" }}>{runId}</code>
          </div>
          <Button variant="ghost" size="sm" onClick={close}>close</Button>
        </div>

        <div className="kit-kv">
          <Badge family="run" value="paused" label="paused" />
          <span className="kit-muted" style={{ fontSize: 11 }}>cost: {t.cost}u</span>
          <span className="kit-muted" style={{ fontSize: 11 }}>{t.actor}</span>
        </div>

        <div className="kit-section">
          <h4>Pending approval</h4>
          <ApprovalCard requestId="hitl_req_204" actor={t.actor} verb="payment.refund" consequence="high"
            inputs={{ amount: 480, currency: "USD", ticket: "T-1192" }}
            reason="Refund exceeds the auto-approve limit ($250)."
            state={decided || "pending"} notes={notes} onNotesChange={setNotes}
            onApprove={() => setDecided("approved")} onReject={() => setDecided("rejected")} />
        </div>

        <div className="kit-section">
          <h4>Live event stream</h4>
          <div className="kit-stream">
            <ReasoningBlock defaultOpen={false}>Order T-1192 confirmed damaged-on-arrival; a refund is warranted. The amount is over my limit, so I'm requesting a human.</ReasoningBlock>
            <ToolCard verb="web.fetch" consequence="high" status="ok" input={{ url: "/orders/T-1192" }} output={{ status: 200, total: 480, state: "damaged" }} />
            <SubagentCard task="Assess damage evidence" skills={["web.search","vision.inspect"]} childRunId="run_7fk2a9d1.1" onOpenRun={openRun} />
            <ToolCard verb="payment.refund" consequence="high" status="running" input={{ amount: 480, currency: "USD" }} />
          </div>
        </div>

        <div className="kit-section">
          <h4>Execution tree</h4>
          <ul className="kit-tree kit-tree--root"><TreeNode node={t} /></ul>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { HomeScreen, ApprovalsScreen, RunDrawer });
