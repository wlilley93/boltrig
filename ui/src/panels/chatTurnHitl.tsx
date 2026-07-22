// Inline HITL. The same request also surfaces in the Approvals panel and the
// Run inspector. All three use the same response controller and two-step
// fixed-option ritual, so an approval never becomes a one-click action merely
// because it was encountered in chat.

import type { HitlEntry } from "@/panels/chatTurnTypes";
import { HitlRespond } from "@/panels/approvalsPanel/HitlRespond";
import { decisionOptions } from "@/panels/approvalsPanel/hitlUtils";
import { useHitlCard } from "@/panels/approvalsPanel/useHitlCard";
import { CONSEQUENCE, HITL_TYPE, StatusBadge } from "@/panels/ux";

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
    <article className={`chat-hitl chat-hitl--${entry.kind}`}>
      <div className="chat-hitl__head">
        <StatusBadge value={entry.kind} glossary={HITL_TYPE} />
        {entry.kind === "approval" && (
          <StatusBadge value="high" glossary={CONSEQUENCE} />
        )}
        {entry.verb && <code className="badge badge--verb">{entry.verb}</code>}
        <code className="muted">{entry.hitlRequestId}</code>
      </div>
      {entry.requestedBy && (
        <p className="chat-hitl__actor">
          Requested by <code>{entry.requestedBy}</code>
        </p>
      )}
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
