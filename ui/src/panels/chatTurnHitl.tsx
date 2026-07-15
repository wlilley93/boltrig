// Inline HITL. The same request also surfaces in the Approvals panel and the
// Run inspector. All three use the same response controller and two-step
// fixed-option ritual, so an approval never becomes a one-click action merely
// because it was encountered in chat.

import type { HitlEntry } from "@/panels/chatTurnTypes";
import { HitlRespond } from "@/panels/approvalsPanel/HitlRespond";
import { decisionOptions } from "@/panels/approvalsPanel/hitlUtils";
import { useHitlCard } from "@/panels/approvalsPanel/useHitlCard";

export function ChatHitlCard({
  entry,
  resolved,
  onResolve,
}: {
  entry: HitlEntry;
  resolved: string | undefined;
  onResolve: (id: string, status: string) => void;
}) {
  const response = useHitlCard(
    { id: entry.hitlRequestId, type: entry.kind },
    () => onResolve(entry.hitlRequestId, "recorded"),
  );

  return (
    <article className="chat-hitl">
      <div className="chat-hitl__head">
        <span className={`badge badge--type badge--type-${entry.kind}`}>
          {entry.kind}
        </span>
        <code className="muted">{entry.hitlRequestId}</code>
      </div>
      <p className="chat-hitl__question">{entry.question || "(no question)"}</p>

      {resolved ? (
        <p className="ok">Answered: {resolved}</p>
      ) : (
        <HitlRespond
          options={decisionOptions(entry.kind, entry.options)}
          h={response}
          showNotes={entry.kind !== "question"}
        />
      )}
    </article>
  );
}
