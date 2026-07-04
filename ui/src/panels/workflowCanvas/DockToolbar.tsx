// Bottom-centre floating dock for the automations canvas (design brief sec
// 22.6). A blurred pill with a Plus button (toggles the node drawer), zoom
// controls wired to the React Flow instance, a fit-view button, and a console
// toggle. The grab/zoom viewport itself is still React Flow.

import { useReactFlow } from "@xyflow/react";

interface DockToolbarProps {
  drawerOpen: boolean;
  onToggleDrawer: () => void;
  consoleOpen: boolean;
  onToggleConsole: () => void;
}

export function DockToolbar({
  drawerOpen,
  onToggleDrawer,
  consoleOpen,
  onToggleConsole,
}: DockToolbarProps) {
  const { zoomIn, zoomOut, fitView } = useReactFlow();

  return (
    <div className="wf3-dock" role="toolbar" aria-label="canvas controls">
      <button
        type="button"
        className={`wf3-dock__plus ${drawerOpen ? "is-active" : ""}`}
        onClick={onToggleDrawer}
        title="Add node"
        aria-pressed={drawerOpen}
      >
        +
      </button>
      <span className="wf3-dock__divider" />
      <button
        type="button"
        className="wf3-dock__btn"
        onClick={() => zoomIn({ duration: 200 })}
        title="Zoom in"
        aria-label="Zoom in"
      >
        <DockGlyph kind="zoomIn" />
      </button>
      <button
        type="button"
        className="wf3-dock__btn"
        onClick={() => zoomOut({ duration: 200 })}
        title="Zoom out"
        aria-label="Zoom out"
      >
        <DockGlyph kind="zoomOut" />
      </button>
      <button
        type="button"
        className="wf3-dock__btn"
        onClick={() => fitView({ duration: 200, padding: 0.2 })}
        title="Fit view"
        aria-label="Fit view"
      >
        <DockGlyph kind="fit" />
      </button>
      <span className="wf3-dock__divider" />
      <button
        type="button"
        className={`wf3-dock__btn ${consoleOpen ? "is-active" : ""}`}
        onClick={onToggleConsole}
        title="Console"
        aria-pressed={consoleOpen}
        aria-label="Toggle console"
      >
        <DockGlyph kind="console" />
      </button>
    </div>
  );
}

function DockGlyph({ kind }: { kind: "zoomIn" | "zoomOut" | "fit" | "console" }) {
  const common = {
    width: 16,
    height: 16,
    viewBox: "0 0 24 24",
    fill: "none",
    xmlns: "http://www.w3.org/2000/svg",
  } as const;
  if (kind === "zoomIn") {
    return (
      <svg {...common}>
        <circle cx="11" cy="11" r="6.5" stroke="currentColor" strokeWidth="1.8" />
        <path d="M11 8v6M8 11h6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        <path d="m20 20-4-4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    );
  }
  if (kind === "zoomOut") {
    return (
      <svg {...common}>
        <circle cx="11" cy="11" r="6.5" stroke="currentColor" strokeWidth="1.8" />
        <path d="M8 11h6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        <path d="m20 20-4-4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    );
  }
  if (kind === "fit") {
    return (
      <svg {...common}>
        <path
          d="M4 9V5a1 1 0 0 1 1-1h4M20 9V5a1 1 0 0 0-1-1h-4M4 15v4a1 1 0 0 0 1 1h4M20 15v4a1 1 0 0 1-1 1h-4"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <path
        d="M5 5h14v11l-4 4H5V5Z"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinejoin="round"
      />
      <path d="M8 9h8M8 12h8M8 15h4" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}
