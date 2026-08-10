import type { SubagentEntry } from "@wlilley93/boltrig-web-sdk";

import { FamiliarBadge } from "../familiar/FamiliarBadge";

interface SubagentChipsProps {
  subagents: SubagentEntry[];
  /** The parent turn has settled (durable transcript or ended live turn). */
  turnEnded: boolean;
  /** Developer detail: monospace skill/policy chips on fan-out rows. */
  tech: boolean;
  /** Mount point for the subagent tab strip (SubagentTabs): when provided,
      every chip and fan-out row becomes a button that opens that subagent's
      own pane. Absent, the rows render as plain rows - never a dead button. */
  onOpenSubagent?(agent: SubagentEntry): void;
}

function badgeState(agent: SubagentEntry, turnEnded: boolean): "ready" | "working" {
  if (agent.status && agent.status !== "running") return "ready";
  return turnEnded ? "ready" : "working";
}

/** The settled state word. `status` is set only by a `subagent_end` frame, so
 * an un-upgraded kernel that never emits one honestly shows nothing settled:
 * "working" while the turn is live, and no claim at all once it is not. */
function stateWord(agent: SubagentEntry, turnEnded: boolean): {
  word: string;
  tone?: "red" | "amber" | "muted";
} {
  if (agent.status === "ok") return { word: "finished" };
  if (agent.status === "error") return { word: "failed", tone: "red" };
  if (agent.status === "degraded") return { word: "degraded", tone: "amber" };
  if (!turnEnded) return { word: "working", tone: "muted" };
  return { word: "" };
}

export function SubagentChips({
  subagents,
  turnEnded,
  tech,
  onOpenSubagent,
}: SubagentChipsProps) {
  if (subagents.length === 0) return null;
  const shown = subagents.slice(0, 3);
  const rest = subagents.slice(3);
  // The tail only claims "finished" when every remaining subagent actually
  // reported a settle frame; otherwise it counts without a verdict.
  const restLabel = rest.length === 0
    ? ""
    : rest.every((agent) => agent.status && agent.status !== "running")
      ? `and ${rest.length} other ${rest.length === 1 ? "subagent" : "subagents"} finished`
      : `and ${rest.length} more ${rest.length === 1 ? "subagent" : "subagents"}`;

  return (
    <>
      <div className="subagent-chips">
        {shown.map((agent) => {
          const inner = (
            <>
              <FamiliarBadge
                state={badgeState(agent, turnEnded)}
                genotype={agent.familiarGenotype}
                label={agent.name ?? agent.task}
              />
              <span>{agent.name ?? agent.task}</span>
            </>
          );
          if (!onOpenSubagent) {
            return <span className="subagent-chip" key={agent.key}>{inner}</span>;
          }
          return (
            <button
              aria-label={`Open subagent ${agent.name ?? agent.task}`}
              className="subagent-chip"
              key={agent.key}
              onClick={() => onOpenSubagent(agent)}
              type="button"
            >
              {inner}
            </button>
          );
        })}
        {restLabel && <span className="subagent-chips-rest">{restLabel}</span>}
      </div>
      <div className="subagent-fanout">
        {subagents.map((agent) => {
          const state = stateWord(agent, turnEnded);
          const techBits = [
            ...agent.skills,
            ...(agent.spawnRule ? [`policy ${agent.spawnRule.id}`] : []),
          ];
          const inner = (
            <>
              <FamiliarBadge
                state={badgeState(agent, turnEnded)}
                genotype={agent.familiarGenotype}
                label={agent.name ?? agent.task}
              />
              <span className="subagent-fan-name">{agent.name ?? "Subagent"}</span>
              <span className="subagent-fan-task">{agent.task}</span>
              {tech && techBits.length > 0 && (
                <span className="verb-chip">{techBits.join(" · ")}</span>
              )}
              {state.word && (
                <span className="subagent-fan-state" data-tone={state.tone}>
                  {state.word}
                </span>
              )}
            </>
          );
          if (!onOpenSubagent) {
            return <div className="subagent-fan-row" key={agent.key}>{inner}</div>;
          }
          return (
            <button
              className="subagent-fan-row"
              key={agent.key}
              onClick={() => onOpenSubagent(agent)}
              type="button"
            >
              {inner}
            </button>
          );
        })}
      </div>
    </>
  );
}
