// Collapsible execution console (design brief sec 22.7). A bottom panel whose
// height is adjustable (80-500px) by dragging its top edge. Shows a mono log
// seeded from the active run record's step results, or an empty state. Each
// row is timestamp(60px) + agent name(80px, coloured) + message, with hover.

import { useCallback, useRef, useState } from "react";
import type { WorkflowRunRecord } from "@/api/types";

interface ExecutionConsoleProps {
  open: boolean;
  onClose: () => void;
  runResult: WorkflowRunRecord | null;
}

interface LogLine {
  time: string;
  agent: string;
  message: string;
  status: string;
}

function statusClass(status: string): string {
  if (["ok", "failed", "error", "paused", "skipped", "running", "exception"].includes(status)) {
    return `wf3-console__agent--${status}`;
  }
  return "wf3-console__agent--default";
}

function linesFromRun(run: WorkflowRunRecord | null): LogLine[] {
  if (!run) return [];
  return run.steps.map((s, i) => ({
    time: `#${i + 1}`,
    agent: s.action || s.id,
    message: s.reason ? `${s.status}: ${s.reason}` : s.status,
    status: s.status,
  }));
}

export function ExecutionConsole({ open, onClose, runResult }: ExecutionConsoleProps) {
  const [height, setHeight] = useState(180);
  const dragging = useRef(false);

  const onDragStart = useCallback(() => {
    dragging.current = true;
    const onMove = (e: MouseEvent) => {
      if (!dragging.current) return;
      const next = window.innerHeight - e.clientY;
      setHeight(Math.min(500, Math.max(80, next)));
    };
    const onUp = () => {
      dragging.current = false;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, []);

  if (!open) return null;
  const lines = linesFromRun(runResult);

  return (
    <div className="wf3-console" style={{ height }}>
      <div className="wf3-console__handle" onMouseDown={onDragStart} title="Drag to resize" />
      <header className="wf3-console__head">
        <span className="wf3-console__title">Console</span>
        <span className="wf3-console__count muted">{lines.length} events</span>
        {(runResult?.exceptions_count ?? 0) > 0 && (
          <span
            className="wf3-console__exceptions"
            title="Failures absorbed by step error strategies or loop error modes - the run completed, but not cleanly"
          >
            {runResult!.exceptions_count} recovered
          </span>
        )}
        <button type="button" className="wf3-console__close" onClick={onClose} aria-label="Close console">
          x
        </button>
      </header>
      <div className="wf3-console__body">
        {lines.length === 0 ? (
          <p className="wf3-console__empty muted">No events yet. Run the workflow to see output.</p>
        ) : (
          lines.map((line, i) => (
            <div className="wf3-console__row" key={i}>
              <span className="wf3-console__time">{line.time}</span>
              <span className={`wf3-console__agent ${statusClass(line.status)}`}>
                {line.agent}
              </span>
              <span className="wf3-console__msg">{line.message}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
