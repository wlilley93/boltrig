import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import { approvals as initialApprovals, goals as initialGoals, type Approval, type Goal, type Selection } from "./model";

interface PrototypeContextValue {
  selection: Selection;
  select: (selection: Selection) => void;
  activeConversationId: string;
  theme: "light" | "dark";
  toggleTheme: () => void;
  inspectorOpen: boolean;
  navigatorOpen: boolean;
  openInspector: () => void;
  closeInspector: () => void;
  toggleInspector: () => void;
  toggleNavigator: () => void;
  inspectorWidth: number;
  setInspectorWidth: (width: number) => void;
  goals: Goal[];
  approvals: Approval[];
  stoppedRunIds: readonly string[];
  stopRun: (id: string) => void;
  addGoal: (goal: Goal) => void;
  decideApproval: (id: string, status: "approved" | "rejected") => void;
  published: boolean;
  publish: () => void;
  notice: string;
  notify: (message: string) => void;
}

const PrototypeContext = createContext<PrototypeContextValue | null>(null);

function readTheme(): "light" | "dark" {
  try {
    return window.localStorage.getItem("boltrig-prototype-theme") === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

function persistTheme(theme: "light" | "dark") {
  try {
    window.localStorage.setItem("boltrig-prototype-theme", theme);
  } catch {
    // Storage can be unavailable in hardened or private browser contexts.
  }
}

export function PrototypeProvider({ children }: { children: ReactNode }) {
  const [selection, setSelection] = useState<Selection>({ kind: "goal", id: "goal-beta" });
  const [activeConversationId, setActiveConversationId] = useState("conversation-evidence");
  const [theme, setTheme] = useState<"light" | "dark">(readTheme);
  const [inspectorOpen, setInspectorOpen] = useState(() => window.innerWidth > 760);
  const [navigatorOpen, setNavigatorOpen] = useState(true);
  const [inspectorWidth, setInspectorWidth] = useState(() => window.innerWidth <= 1320 ? 320 : 360);
  const [goals, setGoals] = useState(initialGoals);
  const [approvals, setApprovals] = useState(initialApprovals);
  const [stoppedRunIds, setStoppedRunIds] = useState<string[]>([]);
  const [published, setPublished] = useState(false);
  const [notice, setNotice] = useState("");
  const noticeTimer = useRef<number | undefined>(undefined);
  const inspectorFocusTimer = useRef<number | undefined>(undefined);
  const inspectorOpenRef = useRef(inspectorOpen);
  const inspectorReturnFocus = useRef<HTMLElement | null>(null);

  const rememberInspectorTrigger = useCallback(() => {
    if (document.activeElement instanceof HTMLElement) inspectorReturnFocus.current = document.activeElement;
  }, []);
  const restoreInspectorTrigger = useCallback(() => {
    const target = inspectorReturnFocus.current;
    inspectorReturnFocus.current = null;
    if (!target) return;
    if (inspectorFocusTimer.current !== undefined) window.clearTimeout(inspectorFocusTimer.current);
    inspectorFocusTimer.current = window.setTimeout(() => {
      inspectorFocusTimer.current = undefined;
      if (target.isConnected) target.focus();
    }, 0);
  }, []);
  const openInspector = useCallback(() => {
    if (inspectorFocusTimer.current !== undefined) {
      window.clearTimeout(inspectorFocusTimer.current);
      inspectorFocusTimer.current = undefined;
    }
    if (!inspectorOpenRef.current) rememberInspectorTrigger();
    inspectorOpenRef.current = true;
    setInspectorOpen(true);
  }, [rememberInspectorTrigger]);
  const closeInspector = useCallback(() => {
    if (!inspectorOpenRef.current) return;
    inspectorOpenRef.current = false;
    setInspectorOpen(false);
    restoreInspectorTrigger();
  }, [restoreInspectorTrigger]);
  const toggleInspector = useCallback(() => {
    if (inspectorOpenRef.current) closeInspector();
    else openInspector();
  }, [closeInspector, openInspector]);
  const select = useCallback((next: Selection) => {
    setSelection(next);
    if (next.kind === "conversation") setActiveConversationId(next.id);
    else openInspector();
  }, [openInspector]);

  const notify = useCallback((message: string) => {
    if (noticeTimer.current !== undefined) window.clearTimeout(noticeTimer.current);
    setNotice(message);
    noticeTimer.current = window.setTimeout(() => {
      noticeTimer.current = undefined;
      setNotice("");
    }, 2600);
  }, []);
  const stopRun = useCallback((id: string) => {
    setStoppedRunIds((current) => current.includes(id) ? current : [...current, id]);
    notify("Prototype run stopped at the next checkpoint");
  }, [notify]);

  useEffect(() => () => {
    if (noticeTimer.current !== undefined) window.clearTimeout(noticeTimer.current);
    if (inspectorFocusTimer.current !== undefined) window.clearTimeout(inspectorFocusTimer.current);
  }, []);

  const value = useMemo<PrototypeContextValue>(() => ({
    selection,
    select,
    activeConversationId,
    theme,
    toggleTheme: () => setTheme((current) => {
      const next = current === "light" ? "dark" : "light";
      persistTheme(next);
      return next;
    }),
    inspectorOpen,
    navigatorOpen,
    openInspector,
    closeInspector,
    toggleInspector,
    toggleNavigator: () => setNavigatorOpen((open) => !open),
    inspectorWidth,
    setInspectorWidth: (width) => setInspectorWidth(Math.min(420, Math.max(310, width))),
    goals,
    approvals,
    stoppedRunIds,
    stopRun,
    addGoal: (goal) => {
      setGoals((current) => [goal, ...current]);
      select({ kind: "goal", id: goal.id });
      notify("Goal created in prototype state");
    },
    decideApproval: (id, status) => {
      setApprovals((current) => current.map((approval) => approval.id === id ? { ...approval, status } : approval));
      notify(status === "approved" ? "Approval recorded" : "Request rejected");
    },
    published,
    publish: () => {
      setPublished(true);
      notify("Revision 8 published");
    },
    notice,
    notify,
  }), [selection, select, activeConversationId, theme, inspectorOpen, navigatorOpen, inspectorWidth, goals, approvals, stoppedRunIds, stopRun, published, notice, notify, openInspector, closeInspector, toggleInspector]);

  return <PrototypeContext.Provider value={value}>{children}</PrototypeContext.Provider>;
}

export function usePrototype(): PrototypeContextValue {
  const value = useContext(PrototypeContext);
  if (!value) throw new Error("usePrototype must be used inside PrototypeProvider");
  return value;
}
