import { useEffect, useState } from "react";

import type { ChatEvent } from "@/api/types";
import { openRun } from "@/router";
import { apiReason, cleanTaskText } from "@/panels/shared";
import { AgentAvatar } from "@/panels/chat/AgentAvatar";
import type { ChatAgent } from "@/panels/chat/constants";
import { Icon } from "@/panels/chat/icons";
import { streamRunEvents } from "@/api/client";
import { toolLabel } from "@/panels/chat/text";

interface SubRunPanelProps {
  runId: string | null;
  full: boolean;
  agent: ChatAgent;
  onClose: () => void;
  onFull: () => void;
  onCollapse: () => void;
}

function useSubRunEvents(runId: string | null): {
  events: ChatEvent[];
  loading: boolean;
  error: string | null;
} {
  const [events, setEvents] = useState<ChatEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    let alive = true;
    const ctrl = new AbortController();
    setEvents([]);
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        await streamRunEvents(
          runId,
          (ev) => {
            if (!alive) return;
            setEvents((prev) => [...prev, ev]);
          },
          { signal: ctrl.signal, follow: false },
        );
        if (alive) setLoading(false);
      } catch (err) {
        if (!alive) return;
        setError(apiReason(err));
        setLoading(false);
      }
    })();
    return () => {
      alive = false;
      ctrl.abort();
    };
  }, [runId]);

  return { events, loading, error };
}

function SubRunEvent({ ev }: { ev: ChatEvent }): JSX.Element | null {
  if (ev.type === "text_delta") {
    return <p className="subrun-line subrun-line--text">{ev.delta}</p>;
  }
  if (ev.type === "reasoning_delta") {
    return <p className="subrun-line subrun-line--reasoning">{ev.delta}</p>;
  }
  if (ev.type === "tool_call") {
    const verb = ev.verb || ev.tool || "tool";
    return (
      <div className="subrun-tool">
        <span className="tool-card__dot" />
        <span>{toolLabel(verb)}</span>
      </div>
    );
  }
  if (ev.type === "tool_result") {
    const verb = ev.verb || "tool";
    return (
      <div className="subrun-tool">
        <span className="tool-card__dot" />
        <span>
          {toolLabel(verb)} - {ev.status}
        </span>
      </div>
    );
  }
  if (ev.type === "subagent") {
    return (
      <div className="subrun-line subrun-line--sub">
        <strong>Sub-agent</strong>: {cleanTaskText(ev.task)}
      </div>
    );
  }
  return null;
}

export function SubRunPanel({ runId, full, agent, onClose, onFull, onCollapse }: SubRunPanelProps): JSX.Element | null {
  const { events, loading, error } = useSubRunEvents(runId);
  if (!runId) return null;

  return (
    <aside className={full ? "subrun-panel subrun-panel--full" : "subrun-panel"} aria-label="Sub-run">
      <header className="subrun-panel__head">
        <button className="icon-btn" type="button" onClick={onClose} aria-label="Close sub-run">
          <Icon name="x" size={15} />
        </button>
        <AgentAvatar agent={agent} size={20} status={false} />
        <span>
          <strong>{agent.name}</strong>
          <small>{agent.role}</small>
        </span>
        <button className="btn btn--ghost btn--sm" type="button" onClick={full ? onCollapse : onFull}>
          {full ? "Back" : "Expand"}
        </button>
        <button className="btn btn--ghost btn--sm" type="button" onClick={() => openRun(runId)}>
          Open run
        </button>
      </header>
      <div className="subrun-panel__body">
        {loading && <p className="muted subrun-panel__loading">Loading run events...</p>}
        {error && <p className="error subrun-panel__error">{error}</p>}
        {!loading && !error && events.length === 0 && (
          <p className="muted subrun-panel__empty">
            No retained events were returned for this run.
          </p>
        )}
        {events.map((ev, i) => (
          <SubRunEvent key={i} ev={ev} />
        ))}
      </div>
    </aside>
  );
}

export { type SubRunPanelProps };
