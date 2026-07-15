import { useEffect, useMemo, useRef, useState } from "react";

import { AgentsScreen } from "./screens/AgentsScreen";
import { AutomationsScreen } from "./screens/AutomationsScreen";
import { ChatScreen } from "./screens/ChatScreen";
import { GoalsScreen } from "./screens/GoalsScreen";
import { HomeScreen } from "./screens/HomeScreen";
import { RunsApprovalsScreen } from "./screens/RunsApprovalsScreen";
import { WorkScreen } from "./screens/WorkScreen";
import { EntityInspector } from "./EntityInspector";
import { PrototypeProvider, usePrototype } from "./PrototypeContext";
import { Icon, type IconName } from "./PrototypeIcons";
import { agents, conversations, projects, runs, type PrototypeScreen, workItems, workers } from "./model";
import "./prototype-layout.css";
import "./prototype-components.css";
import "./prototype-detail.css";
import "./prototype-chat.css";

const nav: { id: PrototypeScreen; label: string; icon: IconName }[] = [
  { id: "home", label: "Home", icon: "home" },
  { id: "chat", label: "Chat", icon: "chat" },
  { id: "goals", label: "Goals", icon: "goal" },
  { id: "work", label: "Work", icon: "work" },
  { id: "agents", label: "Agents", icon: "agent" },
  { id: "automations", label: "Automations", icon: "flow" },
  { id: "runs", label: "Runs", icon: "run" },
  { id: "approvals", label: "Approvals", icon: "approval" },
];

const defaultSelection = {
  home: { kind: "goal", id: "goal-beta" },
  chat: { kind: "conversation", id: "conversation-evidence" },
  goals: { kind: "goal", id: "goal-beta" },
  work: { kind: "work", id: "work-142" },
  agents: { kind: "agent", id: "agent-bolt" },
  automations: { kind: "automation", id: "automation-evidence" },
  runs: { kind: "run", id: "run-2048" },
  approvals: { kind: "approval", id: "approval-77" },
} as const;

function currentScreen(): PrototypeScreen {
  const parts = window.location.hash.replace(/^#\/?/, "").split("/");
  const candidate = parts[0] === "prototype" ? parts[1] : undefined;
  return nav.some((item) => item.id === candidate) ? candidate as PrototypeScreen : "home";
}

function usePrototypeRoute() {
  const [screen, setScreen] = useState(currentScreen);
  useEffect(() => {
    const update = () => setScreen(currentScreen());
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  return screen;
}

function Navigator({ screen }: { screen: PrototypeScreen }) {
  const { activeConversationId, approvals: liveApprovals, goals: liveGoals, selection, select } = usePrototype();
  const [query, setQuery] = useState("");
  const heading = screen === "home" ? "Boltrig Labs" : nav.find((item) => item.id === screen)?.label;
  const rows = useMemo(() => {
    if (screen === "goals" || screen === "home") return liveGoals.map((goal) => ({ id: goal.id, kind: "goal" as const, label: goal.title, meta: `${goal.progress}%` }));
    if (screen === "chat") return conversations.map((conversation) => ({ id: conversation.id, kind: "conversation" as const, label: conversation.title, meta: `${conversation.actor} · ${conversation.updated}`, state: conversation.state }));
    if (screen === "work") return workItems.map((work) => ({ id: work.id, kind: "work" as const, label: work.title, meta: work.status.replace("-", " ") }));
    if (screen === "agents") return [...agents.map((agent) => ({ id: agent.id, kind: "agent" as const, label: agent.name, meta: `Tier ${agent.tier}` })), ...workers.map((worker) => ({ id: worker.id, kind: "worker" as const, label: worker.name, meta: worker.status }))];
    if (screen === "automations") return [{ id: "automation-evidence", kind: "automation" as const, label: "Weekly customer evidence digest", meta: "Draft · v8" }, { id: "automation-readiness", kind: "automation" as const, label: "Release readiness check", meta: "Published · v4" }];
    if (screen === "runs") return runs.map((run) => ({ id: run.id, kind: "run" as const, label: run.title, meta: run.status }));
    return liveApprovals.map((approval) => ({ id: approval.id, kind: "approval" as const, label: approval.title, meta: approval.status }));
  }, [screen, liveApprovals, liveGoals]);
  const visibleRows = rows.filter((row) => row.label.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));

  useEffect(() => setQuery(""), [screen]);

  return (
    <aside className="proto-nav" aria-label={`${heading} navigator`}>
      <div className="proto-nav__head">
        <p className="proto-eyebrow">{screen === "home" ? "Organisation" : "Workspace"}</p>
        <h2>{heading}</h2>
      </div>
      <label className="proto-search">
        <Icon name="search" size={15} />
        <span className="sr-only">Search {heading}</span>
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={`Search ${String(heading).toLowerCase()}`} />
      </label>
      {screen === "home" && <div className="proto-mission"><span>Mission</span>Build dependable autonomous operations that remain understandable and governable.</div>}
      <div className="proto-nav__section">
        <span>{screen === "home" || screen === "goals" ? "Goals" : screen === "chat" ? "Conversations" : screen === "agents" ? "Organisation" : "Recent"}</span>
        <div className="proto-nav__rows">
          {visibleRows.map((row) => (
            <button key={row.id} type="button" className={(screen === "chat" ? activeConversationId : selection.id) === row.id ? "is-selected" : ""} aria-pressed={(screen === "chat" ? activeConversationId : selection.id) === row.id} onClick={() => select({ kind: row.kind, id: row.id })}>
              <span>{"state" in row && row.state !== "settled" && <i className={`proto-conv-dot is-${row.state}`} />}{row.label}</span><small>{row.meta}</small>
            </button>
          ))}
          {visibleRows.length === 0 && <p className="proto-nav__empty">No matching items</p>}
        </div>
      </div>
      {screen === "goals" && <div className="proto-nav__section"><span>Projects</span>{projects.map((project) => <button className="proto-nav__project" key={project.id} onClick={() => select({ kind: "project", id: project.id })}>{project.title}<small>{project.confidence}% confidence</small></button>)}</div>}
      <div className="proto-nav__foot"><span className="proto-live-dot" />Prototype data<span>Reset</span></div>
    </aside>
  );
}

function AppRail({ screen }: { screen: PrototypeScreen }) {
  const { approvals: liveApprovals, theme, toggleTheme, toggleInspector, toggleNavigator } = usePrototype();
  const pendingApprovals = liveApprovals.filter((approval) => approval.status === "pending").length;
  return (
    <nav className="proto-rail" aria-label="Primary navigation">
      <a href="#/prototype/home" className="proto-mark" aria-label="Boltrig prototype home"><span>ϟ</span></a>
      <div className="proto-rail__nav">
        {nav.map((item) => <a key={item.id} href={`#/prototype/${item.id}`} className={screen === item.id ? "is-active" : ""} aria-current={screen === item.id ? "page" : undefined} aria-label={item.label} title={item.label}><Icon name={item.icon} /><span>{item.label}</span>{item.id === "approvals" && pendingApprovals > 0 && <b>{pendingApprovals}</b>}</a>)}
      </div>
      <div className="proto-rail__tools">
        <button type="button" onClick={toggleNavigator} aria-label="Toggle navigator" title="Toggle navigator (⌘B)"><Icon name="panel" /></button>
        <button type="button" onClick={toggleInspector} aria-label="Toggle inspector" title="Toggle inspector (⌘I)"><Icon name="panel" /></button>
        <button type="button" onClick={toggleTheme} aria-label="Toggle theme" title="Toggle theme"><Icon name={theme === "light" ? "moon" : "sun"} /></button>
        <div className="proto-avatar" title="Will Lilley">WL</div>
      </div>
    </nav>
  );
}

function Workspace({ screen }: { screen: PrototypeScreen }) {
  if (screen === "home") return <HomeScreen />;
  if (screen === "chat") return <ChatScreen />;
  if (screen === "goals") return <GoalsScreen />;
  if (screen === "work") return <WorkScreen />;
  if (screen === "agents") return <AgentsScreen />;
  if (screen === "automations") return <AutomationsScreen />;
  return <RunsApprovalsScreen mode={screen} />;
}

function PrototypeShell() {
  const screen = usePrototypeRoute();
  const { activeConversationId, theme, closeInspector, inspectorOpen, navigatorOpen, inspectorWidth, setInspectorWidth, notice, select, toggleInspector, toggleNavigator } = usePrototype();
  const dragStart = useRef<{ x: number; width: number } | null>(null);
  const resizeCleanup = useRef<(() => void) | null>(null);

  useEffect(() => {
    select(screen === "chat" ? { kind: "conversation", id: activeConversationId } : defaultSelection[screen]);
    if (window.innerWidth <= 760) closeInspector();
  }, [activeConversationId, closeInspector, screen, select]);

  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      const target = event.target;
      if (event.repeat || (target instanceof HTMLElement && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)))) return;
      if (!event.metaKey && !event.ctrlKey) return;
      if (event.key.toLowerCase() === "i") { event.preventDefault(); toggleInspector(); }
      if (event.key.toLowerCase() === "b") { event.preventDefault(); toggleNavigator(); }
      const index = Number(event.key) - 1;
      if (index >= 0 && index < nav.length) {
        event.preventDefault();
        window.location.hash = `#/prototype/${nav[index].id}`;
      }
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [toggleInspector, toggleNavigator]);

  useEffect(() => () => resizeCleanup.current?.(), []);

  const beginResize = (event: React.PointerEvent) => {
    event.preventDefault();
    resizeCleanup.current?.();
    dragStart.current = { x: event.clientX, width: inspectorWidth };
    const move = (moveEvent: PointerEvent) => {
      if (dragStart.current) setInspectorWidth(dragStart.current.width + dragStart.current.x - moveEvent.clientX);
    };
    const up = () => {
      dragStart.current = null;
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
      window.removeEventListener("blur", up);
      resizeCleanup.current = null;
    };
    resizeCleanup.current = up;
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
    window.addEventListener("blur", up);
  };

  const resizeWithKeyboard = (event: React.KeyboardEvent) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    setInspectorWidth(inspectorWidth + (event.key === "ArrowLeft" ? 10 : -10));
  };

  return (
    <div className={`proto-app proto-app--${theme}`} style={{ "--inspector-width": `${inspectorWidth}px` } as React.CSSProperties}>
      <AppRail screen={screen} />
      {navigatorOpen && <Navigator screen={screen} />}
      <main className="proto-workspace"><Workspace screen={screen} /></main>
      {inspectorOpen && <><section className="proto-resizer-region" aria-label="Inspector sizing control"><div className="proto-resizer" role="separator" aria-label="Resize context inspector" aria-orientation="vertical" aria-valuemin={310} aria-valuemax={420} aria-valuenow={inspectorWidth} tabIndex={0} onKeyDown={resizeWithKeyboard} onPointerDown={beginResize} /></section><EntityInspector /></>}
      {notice && <div className="proto-toast" role="status"><Icon name="check" size={16} />{notice}</div>}
    </div>
  );
}

export function PrototypeApp() {
  return <PrototypeProvider><PrototypeShell /></PrototypeProvider>;
}
