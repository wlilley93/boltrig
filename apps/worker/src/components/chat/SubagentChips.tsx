import type { SubagentEntry } from "@wlilley93/boltrig-web-sdk";

import { FamiliarBadge } from "../familiar/FamiliarBadge";
import "./TranscriptDensity.css";

interface SubagentChipsProps {
  subagents: SubagentEntry[];
  /** The parent turn has settled (durable transcript or ended live turn). */
  turnEnded: boolean;
  /** Developer detail: real skills/policy receipts stay compact in the chip. */
  tech: boolean;
  /** When provided, each chip opens the real subagent pane. Without it the
      chip is static rather than becoming a dead button. */
  onOpenSubagent?(agent: SubagentEntry): void;
}

function badgeState(agent: SubagentEntry, turnEnded: boolean): "ready" | "working" {
  if (agent.status === "running") return "working";
  if (agent.status) return "ready";
  return turnEnded ? "ready" : "working";
}

/** Only claim a state the event contract actually supplied. An ended parent
 * with no subagent_end has no visible state word; it must not become updated. */
function stateWord(agent: SubagentEntry, turnEnded: boolean): {
  word: string;
  tone?: "red" | "amber" | "muted";
} {
  if (agent.status === "ok") return { word: "updated" };
  if (agent.status === "error") return { word: "failed", tone: "red" };
  if (agent.status === "degraded") return { word: "degraded", tone: "amber" };
  if (agent.status === "running" || !turnEnded) return { word: "working", tone: "muted" };
  return { word: "" };
}

function groupState(subagents: SubagentEntry[], turnEnded: boolean): {
  label: string;
  tone?: "red" | "amber" | "muted";
} | null {
  const words = subagents.map((agent) => stateWord(agent, turnEnded));
  const known = words.filter((state) => state.word);
  if (known.length === 0) return null;
  const unique = [...new Set(known.map((state) => state.word))];
  if (known.length === subagents.length && unique.length === 1) {
    return { label: unique[0]!, tone: known[0]!.tone };
  }
  const order = ["updated", "working", "degraded", "failed"];
  const parts = order.flatMap((word) => {
    const count = known.filter((state) => state.word === word).length;
    return count > 0 ? [`${count} ${word}`] : [];
  });
  const unknown = subagents.length - known.length;
  if (unknown > 0) parts.push(`${unknown} status unknown`);
  return {
    label: parts.join(", "),
    tone: known.some((state) => state.tone === "red")
      ? "red"
      : known.some((state) => state.tone === "amber")
        ? "amber"
        : "muted",
  };
}

export function SubagentChips({
  subagents,
  turnEnded,
  tech,
  onOpenSubagent,
}: SubagentChipsProps) {
  if (subagents.length === 0) return null;
  const aggregate = groupState(subagents, turnEnded);
  return (
    <div className="subagent-chips transcript-subagent-chips">
      {subagents.map((agent) => {
        const name = agent.name ?? agent.task;
        const state = stateWord(agent, turnEnded);
        const techBits = [
          ...agent.skills,
          ...(agent.spawnRule ? [`policy ${agent.spawnRule.id}`] : []),
        ];
        const accessible = [
          name,
          agent.name ? agent.task : "",
          state.word,
          tech && techBits.length > 0 ? techBits.join(", ") : "",
        ].filter(Boolean).join(" · ");
        const inner = (
          <>
            <FamiliarBadge
              decorative
              state={badgeState(agent, turnEnded)}
              genotype={agent.familiarGenotype}
              label={name}
            />
            <span className="transcript-subagent-name">{name}</span>
            {tech && techBits.length > 0 && (
              <code className="transcript-subagent-tech">{techBits.join(" · ")}</code>
            )}
          </>
        );
        if (!onOpenSubagent) {
          const supplemental = [
            agent.name ? agent.task : "",
            state.word,
            tech && techBits.length > 0 ? techBits.join(", ") : "",
          ].filter(Boolean).join(" · ");
          return (
            <span className="subagent-chip transcript-subagent-chip" key={agent.key}>
              {inner}
              {supplemental && (
                <span className="transcript-subagent-sr">{supplemental}</span>
              )}
            </span>
          );
        }
        return (
          <button
            aria-label={`Open subagent ${accessible}`}
            className="subagent-chip transcript-subagent-chip"
            key={agent.key}
            onClick={() => onOpenSubagent(agent)}
            title={agent.task}
            type="button"
          >
            {inner}
          </button>
        );
      })}
      {aggregate && (
        <small className="transcript-subagent-group-state" data-tone={aggregate.tone}>
          {aggregate.label}
        </small>
      )}
    </div>
  );
}
