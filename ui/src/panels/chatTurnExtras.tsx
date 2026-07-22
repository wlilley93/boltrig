// Composes the extra content of a streamed turn: reasoning, workflow steps,
// tool cards, sub-agent cards, and inline HITL / question cards.

import { useEffect, useState } from "react";

import type { NormalizedTurn } from "@/panels/chatTurnTypes";
import { ChatHitlCard } from "@/panels/chatTurnHitl";
import { ChatQuestionCard } from "@/panels/chatTurnQuestion";
import { StepsCard } from "@/panels/chatTurnSteps";
import { SubagentCard } from "@/panels/chatTurnSubagent";
import { ToolCard } from "@/panels/chatTurnToolCard";

const SUBAGENT_COLORS = [
  "var(--color-accent-2)",
  "var(--color-accent)",
];

function ReasoningDisclosure({
  reasoning,
  active,
}: {
  reasoning: string;
  active: boolean;
}) {
  const [open, setOpen] = useState(active);
  const [userToggled, setUserToggled] = useState(false);

  useEffect(() => {
    if (!userToggled) setOpen(active);
  }, [active, userToggled]);

  return (
    <details
      className="thinking"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary
        className="thinking__label"
        onClick={() => setUserToggled(true)}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") setUserToggled(true);
        }}
      >
        <span>Thinking</span>
        <span className="thinking__count">{reasoning.length} chars</span>
      </summary>
      <div className="thinking__body">{reasoning}</div>
    </details>
  );
}

export function TurnExtras({
  turn,
  resolvedHitls,
  onResolve,
  onOpenRun,
}: {
  turn: NormalizedTurn;
  resolvedHitls: Record<string, string>;
  onResolve: (id: string, status: string) => void;
  onOpenRun?: (runId: string) => void;
}) {
  return (
    <>
      {turn.reasoning && (
        <ReasoningDisclosure
          reasoning={turn.reasoning}
          active={!turn.text && !turn.ended && !turn.cancelled}
        />
      )}
      {turn.timeline.map((item, index) => {
        switch (item.kind) {
          case "tool":
            return <ToolCard key={item.key} tool={item.entry} />;
          case "subagent":
            return (
              <SubagentCard
                key={item.key}
                sub={item.entry}
                color={SUBAGENT_COLORS[index % SUBAGENT_COLORS.length]}
                onOpenRun={onOpenRun}
              />
            );
          case "hitl":
            return (
              <ChatHitlCard
                key={item.key}
                entry={item.entry}
                resolved={resolvedHitls[item.entry.hitlRequestId]}
                onResolve={onResolve}
              />
            );
          case "question":
            return (
              <ChatQuestionCard
                key={item.key}
                entry={item.entry}
                resolved={resolvedHitls[item.entry.questionId]}
                onResolve={onResolve}
              />
            );
          case "steps":
            return <StepsCard key={item.key} steps={item.entries} />;
        }
      })}
    </>
  );
}
