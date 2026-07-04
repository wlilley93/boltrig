// Composes the extra content of a streamed turn: reasoning, workflow steps,
// tool cards, sub-agent cards, and inline HITL / question cards.

import type { NormalizedTurn } from "@/panels/chatTurnTypes";
import { ChatHitlCard } from "@/panels/chatTurnHitl";
import { ChatQuestionCard } from "@/panels/chatTurnQuestion";
import { StepsCard } from "@/panels/chatTurnSteps";
import { SubagentCard } from "@/panels/chatTurnSubagent";
import { ToolCard } from "@/panels/chatTurnToolCard";

const SUBAGENT_COLORS = ["#5E69DD", "#FF7A45", "#7C8BFF", "#3FB984", "#3DD3F0"];

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
        <div className="thinking">
          <span className="thinking__label">thinking</span>
          <div className="thinking__body">{turn.reasoning}</div>
        </div>
      )}
      {turn.steps.length > 0 && <StepsCard steps={turn.steps} />}
      {turn.tools.map((t) => (
        <ToolCard key={t.key} tool={t} />
      ))}
      {turn.subagents.map((s, i) => (
        <SubagentCard
          key={s.key}
          sub={s}
          color={SUBAGENT_COLORS[i % SUBAGENT_COLORS.length]}
          onOpenRun={onOpenRun}
        />
      ))}
      {turn.hitls.map((h) => (
        <ChatHitlCard
          key={h.hitlRequestId}
          entry={h}
          resolved={resolvedHitls[h.hitlRequestId]}
          onResolve={onResolve}
        />
      ))}
      {turn.questions.map((q) => (
        <ChatQuestionCard
          key={q.questionId}
          entry={q}
          resolved={resolvedHitls[q.questionId]}
          onResolve={onResolve}
        />
      ))}
    </>
  );
}
