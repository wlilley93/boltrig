import type { ChatMessage } from "@wlilley93/boltrig-web-sdk";

function moved(ids: string[], index: number, nextIndex: number): string[] {
  const next = [...ids];
  const [id] = next.splice(index, 1);
  if (id) next.splice(nextIndex, 0, id);
  return next;
}

export function MobileQueuedMessages({
  disabled,
  messages,
  onReorder,
  onSteer,
}: {
  disabled: boolean;
  messages: ChatMessage[];
  onReorder(expectedMessageIds: string[], messageIds: string[]): void | Promise<void>;
  onSteer(message: ChatMessage): void;
}) {
  if (messages.length === 0) return null;
  const ids = messages.map((message) => message.id);
  return (
    <section aria-label="Queued messages" className="m-queued">
      <h2>{messages.length} queued</h2>
      <div className="m-queued-list">
        {messages.map((message, index) => {
          const label = message.content || "Queued instruction";
          return (
            <div className="m-queued-row" key={message.id}>
              <p>{label}</p>
              <div className="m-queued-actions">
                {messages.length > 1 && (
                  <>
                    <button
                      aria-label={`Move queued message earlier: ${label}`}
                      disabled={disabled || index === 0}
                      onClick={() => void onReorder(ids, moved(ids, index, index - 1))}
                      type="button"
                    >↑</button>
                    <button
                      aria-label={`Move queued message later: ${label}`}
                      disabled={disabled || index === messages.length - 1}
                      onClick={() => void onReorder(ids, moved(ids, index, index + 1))}
                      type="button"
                    >↓</button>
                  </>
                )}
                <button
                  aria-label={`Steer queued message: ${label}`}
                  onClick={() => onSteer(message)}
                  type="button"
                >Steer</button>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
