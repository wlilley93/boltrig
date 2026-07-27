// When onOpenRun is provided the child run id becomes a handle that raises the
// Run drawer keyed by it, so a viewer can descend the run tree the backbone
// nests (the consumer-side run nesting).

import type { CSSProperties } from "react";
import { Familiar, familiarAvailable } from "@/familiar/Familiar";
import { stableAgentKey } from "@/familiar/genotype";
import type { SubagentEntry } from "@/panels/chatTurnTypes";
import { cleanTaskText } from "@/panels/shared";

function initialsOf(name: string): string {
  const letter = name.trim().charAt(0).toUpperCase();
  return letter || "?";
}

export function SubagentCard({
  sub,
  color,
  onOpenRun,
}: {
  sub: SubagentEntry;
  color?: string;
  onOpenRun?: (runId: string) => void;
}) {
  // Runtime identity remains textual; one semantic palette keeps heterogeneous
  // providers visually within the same instrument. Name and initials still
  // come from the event when present.
  const agentColor = color ?? "var(--color-accent-2)";
  const name = sub.name ?? "Sub-agent";
  const role = sub.role ?? "ephemeral";
  const initials = sub.initials ?? initialsOf(name);
  const stepCount = sub.stepCount ?? sub.skills.length;

  // A fan-out is exactly where the familiar earns its place: three subagents called "Third
  // architecture", "Third observability" and "Third reliability" are almost unreadable as
  // names and instantly separable as shapes.
  //
  // The key is the NAME, never sub.childRunId - see stableAgentKey. An unnamed subagent
  // derives from its role alone, so it looks like its kind without claiming to be a
  // particular individual.
  const key = stableAgentKey({ name: sub.name, runId: sub.childRunId });
  const showFamiliar = familiarAvailable();

  return (
    <div
      className="subagent-card"
      style={{ "--agent-color": agentColor } as CSSProperties}
    >
      <div className="subagent-card__head">
        {showFamiliar ? (
          <span className="subagent-card__avatar subagent-card__avatar--familiar">
            <Familiar
              agent={{ id: key ?? `role:${role}`, role }}
              size={24}
              run={{ status: "running" }}
              title={`${name}, ${role}`}
            />
          </span>
        ) : (
          <span className="subagent-card__avatar" style={{ background: agentColor }}>
            {initials}
          </span>
        )}
        <span className="subagent-card__meta">
          <span className="subagent-card__name" style={{ color: agentColor }}>
            {name}
          </span>
          <span className="subagent-card__role">{role}</span>
        </span>
        <span className="subagent-card__task">{cleanTaskText(sub.task) || "(no task)"}</span>
        <span className="subagent-card__steps">{stepCount}</span>
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
