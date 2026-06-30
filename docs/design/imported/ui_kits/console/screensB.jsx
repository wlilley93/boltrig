const DSB = window.BoltrigDesignSystem_9308d4;
const KD = window.KIT_DATA;
const NODE_W = 184, NODE_H = 74;

// ---- Canvas edge ----------------------------------------------------------
function Edge({ from, to, live }) {
  const x1 = from.x + NODE_W, y1 = from.y + NODE_H / 2;
  const x2 = to.x, y2 = to.y + NODE_H / 2;
  const len = Math.hypot(x2 - x1, y2 - y1);
  const ang = Math.atan2(y2 - y1, x2 - x1) * 180 / Math.PI;
  return (
    <div className={"kit-edge" + (live ? " kit-edge--live" : "")}
      style={{ left: x1, top: y1, width: len, transform: `rotate(${ang}deg)` }} />
  );
}

function Canvas({ nodes, edges, runState, liveEdges, onNodeClick, selected }) {
  const kindColor = { kernel:"rgba(78,99,126,0.9)", service:"var(--color-node-service)", agent:"var(--color-node-agent)", trigger:"var(--color-node-trigger)" };
  return (
    <div className="kit-canvas">
      <div className="kit-canvas__nodes">
        {edges.map((e, i) => {
          const from = nodes.find((n) => n.id === e.from);
          const to   = nodes.find((n) => n.id === e.to);
          const live = liveEdges && (runState?.[e.from] === "ok" || runState?.[e.from] === "running") && runState?.[e.to] === "running";
          return <Edge key={i} from={from} to={to} live={!!live} />;
        })}
        {nodes.map((n) => (
          <div className="kit-node-abs" key={n.id} style={{ left: n.x, top: n.y, width: NODE_W }}>
            <DSB.Node kind={n.kind} label={n.label} verbId={n.verbId}
              consequence={n.consequence}
              runState={runState ? runState[n.id] : undefined}
              selected={selected === n.id}
              onClick={() => onNodeClick && onNodeClick(n)}
              style={{ cursor: "pointer" }} />
          </div>
        ))}
      </div>
      <div className="kit-canvas__ctrls"><button>+</button><button>-</button><button>[]</button></div>
      <div className="kit-minimap">
        {nodes.map((n) => (
          <i key={n.id} style={{ left: n.x/9, top: n.y/8+6, width: 13, height: 5, background: kindColor[n.kind], borderRadius: 0 }} />
        ))}
      </div>
    </div>
  );
}

// ---- Chat (live turn mid-run) ---------------------------------------------
function ChatScreen({ openRun }) {
  const [text, setText] = React.useState("");
  const full = "I've confirmed order T-1192 arrived damaged, so a refund of $480 is warranted. That's above my auto-approve limit - I've paused the run and raised an approval. The decision is yours.";
  React.useEffect(() => {
    let i = 0;
    const id = setInterval(() => { i += 2; setText(full.slice(0, i)); if (i >= full.length) clearInterval(id); }, 20);
    return () => clearInterval(id);
  }, []);
  const streaming = text.length < full.length;

  return (
    <section className="kit-panel">
      <div className="kit-panel__head">
        <div>
          <h2>Chat</h2>
          <p className="sub" style={{ margin: "6px 0 0" }}>A live transcript of governed agent work.</p>
        </div>
      </div>
      <div className="kit-chat">
        <div className="kit-chat__rail">
          {KD.chatConversations.map((c) => (
            <button key={c.id} className={"kit-conv" + (c.active ? " kit-conv--active" : "")}>
              <span className="kit-conv__title">{c.title}</span>
              <span className="kit-conv__meta kit-muted"><code className="kit-mono" style={{ fontSize: 10 }}>{c.meta}</code></span>
            </button>
          ))}
        </div>
        <div className="kit-chat__main">
          <div className="kit-chat__msgs">
            <div className="kit-msg kit-msg--user">
              <span className="kit-msg__role">you</span>
              <div className="kit-msg__bubble"><div className="kit-msg__text">The customer for T-1192 says it arrived broken. Can you sort the refund?</div></div>
            </div>
            <div className="kit-msg">
              <span className="kit-msg__role">orchestrator &nbsp;&middot;&nbsp; <code className="kit-mono" style={{ fontSize: 10, color: "var(--color-accent)" }}>run_7fk2a9d1</code></span>
              <div className="kit-msg__bubble">
                <DSB.ReasoningBlock>The order is flagged damaged-on-arrival. I'll fetch the order, confirm the amount, then issue a refund - but the amount may exceed my auto-approve limit.</DSB.ReasoningBlock>
                <DSB.ToolCard verb="web.fetch" consequence="high" status="ok"
                  input={{ url: "/api/orders/T-1192" }}
                  output={{ status: 200, total: 480, currency: "USD", state: "damaged-on-arrival" }} />
                <DSB.SubagentCard task="Assess damage evidence from photos" skills={["web.search", "vision.inspect"]} childRunId="run_7fk2a9d1.1" onOpenRun={openRun} />
                <DSB.ApprovalCard requestId="hitl_req_204" actor="agent:support-orchestrator" verb="payment.refund"
                  consequence="high" inputs={{ amount: 480, currency: "USD", ticket: "T-1192" }}
                  reason="Refund exceeds the auto-approve limit ($250)." />
                <div className="kit-msg__text">{text}{streaming ? <span className="kit-cursor" /> : null}</div>
              </div>
            </div>
          </div>
          <div className="kit-chat__composer">
            <textarea className="kit-chat__input" placeholder="Message the orchestrator..." rows={1} />
            <DSB.Button variant="primary">Send</DSB.Button>
          </div>
        </div>
      </div>
    </section>
  );
}

// ---- Workflow (author + live) ---------------------------------------------
function WorkflowScreen({ mode, setMode, openRun }) {
  const wf = KD.workflow;
  const [selected, setSelected] = React.useState("n5");
  const live = mode === "live";
  return (
    <section className="kit-panel">
      <div className="kit-panel__head">
        <div>
          <h2>{live ? "Live run" : "Workflow Studio"}</h2>
          <p className="sub" style={{ margin: "6px 0 0" }}>
            {live ? "The stored graph lighting up as the interpreter walks it." : "Compose verbs into a governed workflow."}
          </p>
        </div>
        <div className="kit-actions">
          <div style={{ display: "inline-flex", border: "1px solid rgba(255,255,255,0.1)", gap: 0 }}>
            <button className={"bds-tab" + (!live ? " bds-tab--active" : "")} style={{ borderRadius: 0, borderBottom: "none" }} onClick={() => setMode("author")}>Author</button>
            <button className={"bds-tab" + (live ? " bds-tab--active" : "")} style={{ borderRadius: 0, borderBottom: "none", borderLeft: "1px solid rgba(255,255,255,0.1)" }} onClick={() => setMode("live")}>Run live</button>
          </div>
          {live
            ? <DSB.Badge family="run" value="running" label="live" />
            : <DSB.Button variant="primary" size="sm">Run workflow</DSB.Button>}
        </div>
      </div>

      <div className={live ? "" : "kit-studio"}>
        {!live && (
          <div className="bds-card">
            <div className="bds-card__head">
              <h3>{wf.name}</h3>
              <code style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--color-text-muted)" }}>{wf.id}</code>
            </div>
            <div className="bds-card__body" style={{ gap: 0 }}>
              <div className="kit-palette-list">
                {KD.capabilities.flatMap((c) => c.verbs).map((v) => (
                  <button key={v.id} className="kit-palette">
                    <code style={{ fontFamily: "var(--font-mono)", fontSize: "var(--fs-sm)" }}>{v.id}</code>
                    <span style={{ marginLeft: "auto" }}>
                      <DSB.Badge family="consequence" value={v.consequence} label={v.consequence} />
                    </span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {live && (
            <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 14px", background: "rgba(255,122,69,0.08)", border: "1px solid rgba(255,122,69,0.3)" }}>
              <DSB.Badge family="run" value="paused" label="paused - needs you" />
              <span style={{ fontSize: "var(--fs-sm)", color: "var(--color-text-secondary)" }}>
                <strong>Issue refund</strong> is waiting on a human approval before executing.
              </span>
              <DSB.Button variant="danger" size="sm" onClick={() => openRun("run_7fk2a9d1")} style={{ marginLeft: "auto" }}>Open run drawer</DSB.Button>
            </div>
          )}
          <Canvas nodes={wf.nodes} edges={wf.edges}
            runState={live ? wf.runState : undefined}
            liveEdges={live}
            selected={!live ? selected : undefined}
            onNodeClick={(n) => { if (live) openRun("run_7fk2a9d1"); else setSelected(n.id); }} />
        </div>
      </div>
    </section>
  );
}

// ---- Router (registry tree) -----------------------------------------------
function RouterScreen() {
  const COL = [40, 316, 596], ROW = 96, Y0 = 28;
  let row = 0; const nodes = []; const edges = [];
  KD.capabilities.forEach((c) => {
    const start = row;
    const centre = start + (c.verbs.length - 1) / 2;
    const nounId = "noun:" + c.noun;
    nodes.push({ id: nounId, tier: "noun", x: COL[0], y: Y0 + centre * ROW, data: { noun: c.noun, count: c.verbs.length } });
    c.verbs.forEach((v) => {
      const y = Y0 + row * ROW;
      const verbId = "verb:" + v.id;
      nodes.push({ id: verbId, tier: "verb", x: COL[1], y, data: v });
      edges.push({ from: nounId, to: verbId, y1: Y0 + centre * ROW, y2: y });
      if (v.binding) {
        const bindId = "bind:" + v.id;
        nodes.push({ id: bindId, tier: "binding", x: COL[2], y, data: v.binding });
        edges.push({ from: verbId, to: bindId, y1: y, y2: y });
      }
      row += 1;
    });
    row += 1;
  });

  return (
    <section className="kit-panel">
      <div className="kit-panel__head">
        <div>
          <h2>Router</h2>
          <p className="sub" style={{ margin: "6px 0 0" }}>Capability registry - noun -&gt; verb -&gt; binding. Your scoped view.</p>
        </div>
      </div>
      <div className="kit-canvas" style={{ height: Math.max(560, 28 + row * 96) }}>
        <div className="kit-canvas__nodes">
          {edges.map((e, i) => {
            const isBound = e.from.startsWith("noun");
            const x1 = isBound ? COL[0] + NODE_W : COL[1] + NODE_W;
            const x2 = isBound ? COL[1] : COL[2];
            const len = Math.hypot(x2 - x1, e.y2 - e.y1);
            const ang = Math.atan2(e.y2 - e.y1, x2 - x1) * 180 / Math.PI;
            return <div key={i} className="kit-edge" style={{ left: x1, top: e.y1 + NODE_H/2, width: len, transform: `rotate(${ang}deg)` }} />;
          })}
          {nodes.map((n) => (
            <div className="kit-node-abs" key={n.id} style={{ left: n.x, top: n.y, width: NODE_W }}>
              {n.tier === "noun"    && <DSB.RegistryNode tier="noun" noun={n.data.noun} count={n.data.count} />}
              {n.tier === "verb"    && <DSB.RegistryNode tier="verb" verbId={n.data.id} consequence={n.data.consequence} health={n.data.health} />}
              {n.tier === "binding" && <DSB.RegistryNode tier="binding" bindingKind={n.data.type === "agent" ? "agent" : "service"} targetType={n.data.type} targetRef={n.data.ref} />}
            </div>
          ))}
        </div>
        <div className="kit-canvas__ctrls"><button>+</button><button>-</button><button>[]</button></div>
      </div>
    </section>
  );
}

// ---- Kanban ---------------------------------------------------------------
function KanbanScreen({ openRun }) {
  const LANES = [["pending","Pending"],["in_flight","In flight"],["blocked","Blocked"],["awaiting_human","Awaiting human"],["done","Done"],["failed","Failed"]];
  const byStatus = {}; LANES.forEach(([s]) => byStatus[s] = []);
  KD.work.forEach((w) => byStatus[w.status].push(w));
  return (
    <section className="kit-panel">
      <div className="kit-panel__head">
        <div><h2>Kanban</h2><p className="sub" style={{ margin: "6px 0 0" }}>{KD.work.length} work items across all lanes.</p></div>
      </div>
      <div className="kit-board">
        {LANES.map(([s, label]) => (
          <div className={"kit-lane kit-lane--" + s} key={s}>
            <div className="kit-lane__head"><span>{label}</span><span className="ct">{byStatus[s].length}</span></div>
            <div className="kit-lane__body">
              {byStatus[s].length === 0
                ? <p className="kit-lane__empty">empty</p>
                : byStatus[s].map((w) => (
                  <article className="kit-work" key={w.id}>
                    <div className="kit-work__intent">{w.intent}</div>
                    <dl className="kit-work__meta">
                      <div><dt>source</dt><dd>{w.source}</dd></div>
                      <div><dt>owner</dt><dd>{w.owner}</dd></div>
                      <div><dt>confidence</dt><dd>{w.confidence == null ? "n/a" : Math.round(w.confidence*100)+"%"}</dd></div>
                      <div><dt>state</dt><dd>{s === "awaiting_human" ? <DSB.Badge family="run" value="paused" label="needs you" /> : s}</dd></div>
                    </dl>
                    <div className="kit-work__foot">
                      {w.runId ? <button className="kit-link" onClick={() => openRun(w.runId)}>run: <code>{w.runId}</code></button> : <span className="kit-muted" style={{ fontSize: 11 }}>no run</span>}
                    </div>
                  </article>
                ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

// ---- Insight (audit table) ------------------------------------------------
function InsightScreen({ openRun }) {
  const rows = [
    { run:"run_7fk2a9d1", actor:"support-orch",  verb:"payment.refund",  conseq:"high", status:"paused", cost:4120, when:"2m ago" },
    { run:"run_5bd0c2a7", actor:"triage.agent",   verb:"ticket.update",   conseq:"low",  status:"ok",     cost:980,  when:"14m ago" },
    { run:"run_2ae91f30", actor:"ops.agent",       verb:"email.send",      conseq:"low",  status:"ok",     cost:220,  when:"1h ago" },
    { run:"run_91x4ke02", actor:"ops.agent",       verb:"payment.charge",  conseq:"high", status:"failed", cost:60,   when:"3h ago" },
    { run:"run_77c0aa12", actor:"research.agent",  verb:"web.fetch",       conseq:"high", status:"ok",     cost:1340, when:"5h ago" },
  ];
  return (
    <section className="kit-panel">
      <div className="kit-panel__head">
        <div><h2>Insight</h2><p className="sub" style={{ margin:"6px 0 0" }}>Cost, audit and runs - scoped to your departments.</p></div>
      </div>
      <div className="kit-table-wrap">
        <table className="kit-table">
          <thead><tr><th>Run</th><th>Actor</th><th>Verb</th><th>Consequence</th><th>Status</th><th>Cost</th><th>When</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.run}>
                <td><button className="kit-link" onClick={() => openRun(r.run)}><code>{r.run}</code></button></td>
                <td style={{ fontFamily:"var(--font-mono)", color:"var(--color-text-muted)", fontSize:12 }}>{r.actor}</td>
                <td><code style={{ fontFamily:"var(--font-mono)", fontSize:12 }}>{r.verb}</code></td>
                <td><DSB.Badge family="consequence" value={r.conseq} label={r.conseq} /></td>
                <td><DSB.Badge family="run" value={r.status} label={r.status} /></td>
                <td style={{ fontFamily:"var(--font-mono)", fontSize:12 }}>{r.cost}u</td>
                <td style={{ color:"var(--color-text-muted)" }}>{r.when}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

Object.assign(window, { ChatScreen, WorkflowScreen, RouterScreen, KanbanScreen, InsightScreen });
