import { ChatHitlCard } from "@/panels/chatTurnHitl";
import type { NormalizedTurn } from "@/panels/chatTurnTypes";

export function RunApprovals({
  turn,
  resolvedHitls,
  onResolve,
}: {
  turn: NormalizedTurn;
  resolvedHitls: Record<string, string>;
  onResolve: (id: string, status: string) => void;
}) {
  const approvals = turn.hitls.filter((entry) => entry.kind === "approval");
  return (
    <div className="run-approvals">
      <h4>Approvals</h4>
      {approvals.length === 0 ? (
        <p className="muted">No approvals at this replay position.</p>
      ) : (
        <div className="run-approvals__list">
          {approvals.map((entry) => (
            <ChatHitlCard
              key={entry.hitlRequestId}
              entry={entry}
              resolved={resolvedHitls[entry.hitlRequestId]}
              onResolve={onResolve}
            />
          ))}
        </div>
      )}
    </div>
  );
}
