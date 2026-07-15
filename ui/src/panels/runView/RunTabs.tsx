import type { KeyboardEvent } from "react";

export type RunTabId =
  | "overview"
  | "timeline"
  | "tree"
  | "tools"
  | "approvals"
  | "raw";

export interface RunTab {
  id: RunTabId;
  label: string;
  count?: number;
}

export function runTabs(toolCount: number, approvalCount: number): RunTab[] {
  const tabs: RunTab[] = [
    { id: "overview", label: "Overview" },
    { id: "timeline", label: "Timeline" },
    { id: "tree", label: "Tree" },
  ];
  if (toolCount > 0) tabs.push({ id: "tools", label: "Tool calls", count: toolCount });
  if (approvalCount > 0) {
    tabs.push({ id: "approvals", label: "Approvals", count: approvalCount });
  }
  tabs.push({ id: "raw", label: "Raw" });
  return tabs;
}

function tabId(id: RunTabId): string {
  return `run-inspector-tab-${id}`;
}

function panelId(id: RunTabId): string {
  return `run-inspector-panel-${id}`;
}

export function RunTabs({
  tabs,
  active,
  onChange,
}: {
  tabs: RunTab[];
  active: RunTabId;
  onChange: (tab: RunTabId) => void;
}) {
  function move(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next: number | null = null;
    if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
    if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = tabs.length - 1;
    if (next === null) return;
    event.preventDefault();
    const nextTab = tabs[next];
    onChange(nextTab.id);
    document.getElementById(tabId(nextTab.id))?.focus();
  }

  return (
    <div className="run-inspector__tabs" role="tablist" aria-label="Run inspector sections">
      {tabs.map((tab, index) => {
        const selected = tab.id === active;
        return (
          <button
            key={tab.id}
            id={tabId(tab.id)}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls={panelId(tab.id)}
            tabIndex={selected ? 0 : -1}
            className={`run-inspector__tab ${selected ? "run-inspector__tab--active" : ""}`}
            onClick={() => onChange(tab.id)}
            onKeyDown={(event) => move(event, index)}
          >
            <span>{tab.label}</span>
            {tab.count !== undefined && (
              <span className="run-inspector__tab-count" aria-label={`${tab.count} items`}>
                {tab.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export function runTabPanelId(id: RunTabId): string {
  return panelId(id);
}

export function runTabButtonId(id: RunTabId): string {
  return tabId(id);
}
