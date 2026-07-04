// When onOpenRun is provided the child run id becomes a handle that raises the
// Run drawer keyed by it, so a viewer can descend the run tree the backbone
// nests (the consumer-side run nesting).

import type { CSSProperties } from "react";
import type { SubagentEntry } from "@/panels/chatTurnTypes";
import { cleanTaskText } from "@/panels/shared";

export function SubagentCard({
  sub,
  color,
  onOpenRun,
}: {
  sub: SubagentEntry;
  color?: string;
  onOpenRun?: (runId: string) => void;
}) {
  const agentColor = color ?? "#5E69DD";
  return (
    <div
      className="subagent-card"
      style={{ "--agent-color": agentColor } as CSSProperties}
    >
      <div className="subagent-card__head">
        <span className="subagent-card__avatar" style={{ background: agentColor }}>
          W
        </span>
        <span className="subagent-card__meta">
          <span className="subagent-card__name">Worker</span>
          <span className="subagent-card__role">ephemeral</span>
        </span>
        <span className="subagent-card__task">{cleanTaskText(sub.task) || "(no task)"}</span>
        <span className="subagent-card__steps">0</span>
        <span className="subagent-card__chevron" aria-hidden="true">
          &#9656;
        </span>
      </div>
      {sub.skills.length > 0 && (
        <div className="subagent-card__skills">
          {sub.skills.map((s) => (
            <span className="chip" key={s}>
              {s}
            </span>
          ))}
        </div>
      )}
      {onOpenRun ? (
        <button
          className="subagent-card__open-run"
          title="Open this sub-agent's run"
          onClick={() => onOpenRun(sub.childRunId)}
        >
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="4" width="18" height="16" rx="1.5" />
            <path d="M15 4v16" />
          </svg>
          Open run
        </button>
      ) : (
        <code className="muted">{sub.childRunId}</code>
      )}
    </div>
  );
}
