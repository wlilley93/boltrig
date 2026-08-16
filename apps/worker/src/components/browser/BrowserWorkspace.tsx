import { useState } from "react";

import { ExactApprovalFinalizer } from "../ExactApprovalFinalizer";
import "./BrowserWorkspace.css";
import type { BrowserFrame, BrowserTab } from "./BrowserWorkspaceModel";
import { useBrowserWorkspace, type BrowserWorkspaceController } from "./useBrowserWorkspace";

export function BrowserWorkspace() {
  const browser = useBrowserWorkspace();
  return (
    <main className="browser-workspace">
      <BrowserToolbar browser={browser} />
      <div className="browser-workspace-body">
        <BrowserViewport browser={browser} />
        <BrowserInspector browser={browser} />
      </div>
      <ExactApprovalFinalizer controller={browser.finalizer} />
    </main>
  );
}

function BrowserToolbar({ browser }: { browser: BrowserWorkspaceController }) {
  return (
    <header className="browser-toolbar">
      <button aria-label="Refresh browser" disabled={browser.busy} onClick={() => void browser.refresh()} type="button">↻</button>
      <form onSubmit={(event) => { event.preventDefault(); void browser.navigate(); }}>
        <input aria-label="Browser address" onChange={(event) => browser.setAddress(event.target.value)} placeholder="https://…" value={browser.address} />
      </form>
      <button disabled={browser.busy || !browser.frame} onClick={() => void browser.inspect()} type="button">Inspect</button>
      <span aria-live="polite" className="browser-status">{browser.busy ? "Working…" : browser.message}</span>
    </header>
  );
}

function BrowserViewport({ browser }: { browser: BrowserWorkspaceController }) {
  if (!browser.frame || !browser.frameSrc) {
    return <section className="browser-viewport empty"><p>{browser.message}</p></section>;
  }
  return (
    <section className="browser-viewport" aria-label="Shared browser">
      <BrowserCanvas browser={browser} frame={browser.frame} />
      <BrowserControls browser={browser} />
    </section>
  );
}

function BrowserCanvas({ browser, frame }: {
  browser: BrowserWorkspaceController;
  frame: BrowserFrame;
}) {
  return (
    <button
      aria-label={`Interact with ${frame.title || "browser page"}`}
      className="browser-canvas"
      disabled={browser.busy}
      onClick={(event) => {
        const rect = event.currentTarget.getBoundingClientRect();
        const x = Math.max(0, Math.min(
          frame.width - 1,
          Math.round(((event.clientX - rect.left) / rect.width) * frame.width),
        ));
        const y = Math.max(0, Math.min(
          frame.height - 1,
          Math.round(((event.clientY - rect.top) / rect.height) * frame.height),
        ));
        void browser.click(x, y);
      }}
      type="button"
    >
      <img alt={frame.title || "Current browser page"} draggable={false} src={browser.frameSrc} />
      {browser.cursor && <span
        aria-hidden
        className={`browser-cursor ${browser.cursor.kind}`}
        key={browser.cursorTick}
        style={{ left: `${(browser.cursor.x / frame.width) * 100}%`, top: `${(browser.cursor.y / frame.height) * 100}%` }}
      />}
    </button>
  );
}

function BrowserControls({ browser }: { browser: BrowserWorkspaceController }) {
  const [text, setText] = useState("");
  return (
    <div className="browser-controls">
      <form onSubmit={(event) => { event.preventDefault(); if (text) void browser.type(text); setText(""); }}>
        <input aria-label="Text to type in browser" onChange={(event) => setText(event.target.value)} placeholder="Type into the focused field" value={text} />
        <button disabled={!text || browser.busy} type="submit">Type</button>
      </form>
      <div className="browser-control-buttons">
        <button onClick={() => void browser.scroll(-540)} type="button">Scroll up</button>
        <button onClick={() => void browser.scroll(540)} type="button">Scroll down</button>
        {(["Tab", "Enter", "Escape"] as const).map((key) => (
          <button key={key} onClick={() => void browser.press(key)} type="button">{key}</button>
        ))}
      </div>
    </div>
  );
}

function BrowserInspector({ browser }: { browser: BrowserWorkspaceController }) {
  return (
    <aside className="browser-inspector" aria-label="Browser details">
      <h2>Tabs</h2>
      <div className="browser-tab-list">
        {browser.tabs.length ? browser.tabs.map((tab) => <BrowserTabRow browser={browser} key={tab.id} tab={tab} />) : <p>No tabs reported.</p>}
      </div>
      <h2>Controls</h2>
      <div className="browser-node-list">
        {browser.nodes.length ? browser.nodes.map((node) => (
          <div className="browser-node" key={node.nodeId}>
            <span>{node.role}</span><strong>{node.name || "Unnamed control"}</strong>
          </div>
        )) : <p>Select Inspect to read the page’s accessible controls.</p>}
      </div>
    </aside>
  );
}

function BrowserTabRow({ browser, tab }: {
  browser: BrowserWorkspaceController;
  tab: BrowserTab;
}) {
  return (
    <div className={tab.url === browser.frame?.url ? "browser-tab-row active" : "browser-tab-row"}>
      <button className="browser-tab-select" disabled={browser.busy} onClick={() => void browser.selectTab(tab.id)} type="button">
        <strong>{tab.title || "Untitled"}</strong><span>{tab.url}</span>
      </button>
      <button aria-label={`Close ${tab.title || "Untitled"} tab`} className="browser-tab-close" disabled={browser.busy} onClick={() => void browser.closeTab(tab.id)} type="button">×</button>
    </div>
  );
}
