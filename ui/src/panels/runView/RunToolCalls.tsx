import { ToolCard } from "@/panels/chatTurnToolCard";
import type { NormalizedTurn } from "@/panels/chatTurnTypes";

export function RunToolCalls({ turn }: { turn: NormalizedTurn }) {
  return (
    <div className="run-tool-calls">
      <h4>Tool calls</h4>
      {turn.tools.length === 0 ? (
        <p className="muted">No tool calls at this replay position.</p>
      ) : (
        <div className="run-tool-calls__list">
          {turn.tools.map((tool) => (
            <ToolCard key={tool.key} tool={tool} />
          ))}
        </div>
      )}
    </div>
  );
}
