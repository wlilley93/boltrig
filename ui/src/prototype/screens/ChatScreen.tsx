import { type FormEvent, useEffect, useRef, useState } from "react";

import { conversations, runs } from "../model";
import { usePrototype } from "../PrototypeContext";
import { Icon } from "../PrototypeIcons";

const starterPrompts = [
  "Turn this outcome into a plan",
  "Delegate a research task",
  "Build a workflow from this conversation",
];

function ConversationOptions({ notify }: { notify: (message: string) => void }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const firstActionRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    firstActionRef.current?.focus();
    const closeOutside = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, [open]);

  const choose = (message: string) => {
    setOpen(false);
    notify(message);
    triggerRef.current?.focus();
  };

  return (
    <div ref={rootRef} className="proto-chat-options">
      <button ref={triggerRef} type="button" className="proto-icon-button" aria-label="Conversation options" aria-controls="proto-chat-conversation-actions" aria-expanded={open} onClick={() => setOpen((current) => !current)}>•••</button>
      {open && <div id="proto-chat-conversation-actions" className="proto-chat-options__panel" role="group" aria-label="Conversation actions" onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); setOpen(false); triggerRef.current?.focus(); } }}><button ref={firstActionRef} type="button" onClick={() => choose("Conversation rename opened in prototype state")}>Rename</button><button type="button" onClick={() => choose("Conversation link copied")}>Copy link</button><button type="button" onClick={() => choose("Conversation archived in prototype state")}>Archive</button></div>}
    </div>
  );
}

function ToolEvent() {
  const [open, setOpen] = useState(true);
  return (
    <details className="proto-chat-event proto-chat-tool" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>
        <span className="proto-chat-event__glyph"><Icon name="check" size={14} /></span>
        <span><b>Loaded current customer evidence</b><small><code>memory.recall</code> · 12 records · governed</small></span>
        <span className="proto-chat-status is-done">Done</span>
      </summary>
      <div className="proto-chat-tool__body">
        <div><span>Scope</span><strong>Design-partner interviews</strong></div>
        <div><span>Result</span><strong>12 reviewed evidence items</strong></div>
        <p>Only scoped, non-sensitive evidence was returned to this run.</p>
      </div>
    </details>
  );
}

function WorkerEvent({ active }: { active: boolean }) {
  const { select } = usePrototype();
  return (
    <div className="proto-chat-event proto-chat-delegation">
      <header><span className="proto-chat-event__glyph is-agent"><Icon name="spark" size={14} /></span><span><b>Delegated to two specialists</b><small>Bounded Tier 3 workers · expire after this run</small></span><span className={`proto-chat-status ${active ? "is-live" : ""}`}>{active ? "Live" : "Stopped"}</span></header>
      <div className="proto-chat-worker-grid">
        <button type="button" onClick={() => select({ kind: "worker", id: "worker-a19f" })}><span className="proto-worker-mini">RS</span><span><b>Research Scout</b><small>Reviewing interview 8 of 12</small></span><em>£0.84</em></button>
        <button type="button" onClick={() => select({ kind: "worker", id: "worker-b720" })}><span className="proto-worker-mini">IS</span><span><b>Interview Synthesiser</b><small>Merging evidence clusters</small></span><em>£0.63</em></button>
      </div>
    </div>
  );
}

function WorkflowDraft({ saved, onSave }: { saved: boolean; onSave: () => void }) {
  return (
    <article className="proto-chat-event proto-chat-workflow">
      <header><span className="proto-chat-event__glyph is-flow"><Icon name="flow" size={14} /></span><span><b>Workflow draft ready</b><small>Weekly customer evidence digest · 7 steps</small></span><span className="proto-chat-status">Draft v8</span></header>
      <div className="proto-chat-flowline" aria-label="Workflow preview">
        <span><i className="is-trigger" />Monday</span><b />
        <span><i className="is-agent" />Research</span><b />
        <span><i className="is-human" />Approve</span><b />
        <span><i className="is-capability" />Publish</span>
      </div>
      <p>It gathers scoped feedback, spawns up to three researchers, merges evidence and pauses before publishing.</p>
      <footer>
        <button type="button" className="proto-button proto-button--secondary" onClick={() => { window.location.hash = "#/prototype/automations"; }}>Open canvas</button>
        <button type="button" className="proto-button proto-button--primary" onClick={onSave}>{saved ? "Saved to Automations" : "Save workflow draft"}</button>
      </footer>
    </article>
  );
}

function ApprovalMoment() {
  const { approvals, decideApproval, select } = usePrototype();
  const approval = approvals.find((item) => item.id === "approval-76");
  const [armed, setArmed] = useState(false);
  const cancelRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (armed) cancelRef.current?.focus();
  }, [armed]);
  if (!approval) return null;
  return (
    <article className={`proto-chat-event proto-chat-approval is-${approval.status}`}>
      <header><span className="proto-chat-event__glyph is-human"><Icon name="approval" size={14} /></span><span><b>{approval.status === "pending" ? "Paused for approval" : `Approval ${approval.status}`}</b><small><code>{approval.verb}</code> · medium consequence</small></span><span className={`proto-chat-status ${approval.status === "pending" ? "is-human" : approval.status === "approved" ? "is-done" : ""}`}>{approval.status === "pending" ? "Needs you" : approval.status === "approved" ? "Recorded" : "Rejected"}</span></header>
      <p>{approval.stakes}</p>
      {approval.status === "pending" && !armed && <footer><button type="button" className="proto-button proto-button--secondary" onClick={() => select({ kind: "approval", id: approval.id })}>Inspect context</button><button type="button" className="proto-button proto-button--primary" onClick={() => setArmed(true)}>Approve</button></footer>}
      {approval.status === "pending" && armed && <div className="proto-chat-confirm" role="group" aria-label="Confirm retention approval" aria-live="polite"><span>Approve retention for this run?</span><button ref={cancelRef} type="button" onClick={() => setArmed(false)}>Cancel</button><button type="button" onClick={() => decideApproval(approval.id, "approved")}>Confirm approval</button></div>}
    </article>
  );
}

function SettledConversation({ conversationId }: { conversationId: string }) {
  const conversation = conversations.find((item) => item.id === conversationId) ?? conversations[0];
  const run = runs.find((item) => item.id === conversation.runId);
  const { select } = usePrototype();
  return (
    <div className="proto-chat-empty-thread">
      <span className="proto-bolt-orb">ϟ</span>
      <h2>{conversation.title}</h2>
      <p>This conversation is settled. Its decisions, delegated work and run evidence remain connected.</p>
      {run && <button type="button" className="proto-button proto-button--secondary" onClick={() => select({ kind: "run", id: run.id })}>Inspect {run.id}</button>}
    </div>
  );
}

export function ChatScreen() {
  const { activeConversationId, notify, select, stoppedRunIds, stopRun } = usePrototype();
  const active = conversations.find((item) => item.id === activeConversationId) ?? conversations[0];
  const [draft, setDraft] = useState("");
  const [sent, setSent] = useState<string[]>([]);
  const [workflowSaved, setWorkflowSaved] = useState(false);
  const [launches, setLaunches] = useState<string[]>([]);
  const [thinkingOpen, setThinkingOpen] = useState(true);
  const runActive = active.runId ? !stoppedRunIds.includes(active.runId) : false;

  const launch = (kind: string, message: string) => {
    setLaunches((current) => current.includes(kind) ? current : [...current, kind]);
    notify(message);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const message = draft.trim();
    if (!message) return;
    setSent((current) => [...current, message]);
    setDraft("");
    notify("Prototype turn added to this conversation");
  };

  return (
    <section className="proto-chat-page">
      <header className="proto-chat-head">
        <div><p className="proto-eyebrow">Conversation</p><h1>{active.title}</h1></div>
        <div className="proto-chat-head__actions"><span className="proto-actor-chip"><i />ϟ Bolt</span>{active.runId && <button type="button" className="proto-chat-run-link" aria-label={`Inspect connected run ${active.runId}`} onClick={() => select({ kind: "run", id: active.runId! })}><Icon name="run" size={14} /><span>Run <code>{active.runId}</code></span></button>}<ConversationOptions notify={notify} /></div>
      </header>

      {active.id !== "conversation-evidence" ? <SettledConversation conversationId={active.id} /> : <>
        <div className="proto-chat-scroll">
          <div className="proto-chat-transcript" role="log" aria-label="Conversation with Bolt" aria-live="polite" aria-relevant="additions text" aria-busy="false">
            <article className="proto-chat-message is-user"><span>You</span><p>Turn our design-partner research into a repeatable weekly evidence brief. Delegate the analysis and make sure nothing publishes without a human.</p></article>
            <article className="proto-chat-message is-assistant">
              <header><span className="proto-bolt-orb">ϟ</span><span><b>Bolt</b><small>Chief of Staff · governed run</small></span>{runActive && active.runId && <button type="button" className="proto-chat-stop" onClick={() => stopRun(active.runId!)}><Icon name="pause" size={13} /> Stop run</button>}</header>
              <details className="proto-chat-thinking" open={thinkingOpen} onToggle={(event) => setThinkingOpen(event.currentTarget.open)}><summary><span />Plan and consequence check complete<small>Scoped before delegation</small></summary><p>I’ll use current evidence, delegate bounded research, propose a reusable workflow and put a human gate immediately before external publication.</p></details>
              <div className="proto-chat-timeline"><ToolEvent /><WorkerEvent active={runActive} /><WorkflowDraft saved={workflowSaved} onSave={() => { setWorkflowSaved(true); launch("workflow", "Workflow draft saved in prototype state"); }} /><ApprovalMoment /></div>
              <div className="proto-chat-answer"><p>I’ve turned this into a governed weekly evidence loop. Research can run autonomously, but publication remains explicitly human-controlled.</p><div className="proto-chat-answer__actions"><button type="button" onClick={() => { launch("work", "Aligned work created in prototype state"); select({ kind: "work", id: "work-142" }); }}><Icon name="work" size={14} />{launches.includes("work") ? "Work created" : "Create aligned work"}</button><button type="button" onClick={() => launch("team", "Specialist team prepared in prototype state")}><Icon name="agent" size={14} />{launches.includes("team") ? "Team prepared" : "Spawn specialist team"}</button><button type="button" onClick={() => { setWorkflowSaved(true); launch("workflow", "Workflow draft saved in prototype state"); }}><Icon name="flow" size={14} />{workflowSaved ? "Workflow saved" : "Save as workflow"}</button></div></div>
            </article>
            {sent.map((message, index) => <div key={`${message}-${index}`} className="proto-chat-followup"><article className="proto-chat-message is-user"><span>You</span><p>{message}</p></article><article className="proto-chat-message is-assistant is-compact"><header><span className="proto-bolt-orb">ϟ</span><span><b>Bolt</b><small>Ready to act</small></span></header><p>I can turn that into governed work, delegate it to the right department, or build a reusable workflow. This prototype keeps the next action deliberate.</p></article></div>)}
          </div>
        </div>
        <div className="proto-chat-composer-wrap">
          <div className="proto-chat-suggestions">{starterPrompts.map((prompt) => <button type="button" key={prompt} onClick={() => setDraft(prompt)}>{prompt}</button>)}</div>
          <form className="proto-chat-composer" onSubmit={submit}>
            <button type="button" aria-label="Add context"><Icon name="plus" size={17} /></button>
            <textarea aria-label="Message Bolt" value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} placeholder="Ask Bolt to plan, delegate or build a workflow…" rows={1} />
            <span>Balanced</span>
            <button type="submit" className="is-send" aria-label="Send message" disabled={!draft.trim()}><Icon name="run" size={16} /></button>
          </form>
          <small>Enter to send · Shift+Enter for a new line · every action stays inside Boltrig’s governed path</small>
        </div>
      </>}
    </section>
  );
}
