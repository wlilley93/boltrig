import type { ChatMessage } from "@wlilley93/boltrig-web-sdk";

export function QueuedMessages({
  messages,
  onSteer,
}: {
  messages: ChatMessage[];
  onSteer(message: ChatMessage): void;
}) {
  return (
    <section aria-label="Queued messages" className="queued-messages">
      {messages.map((message) => (
        <article className="queued-message" data-message-id={message.id} key={message.id}>
          <span aria-hidden className="queued-message-glyph">↳</span>
          <div className="queued-message-copy">
            <p>{message.content || "Queued instruction"}</p>
            {message.attachments && message.attachments.length > 0 && (
              <small>{message.attachments.length} attachment{message.attachments.length === 1 ? "" : "s"}</small>
            )}
          </div>
          <button
            aria-label={`Steer queued message: ${message.content || "Queued instruction"}`}
            className="queued-message-steer"
            onClick={() => onSteer(message)}
            title="Load this queued instruction into the composer"
            type="button"
          >
            ↳ Steer
          </button>
        </article>
      ))}
    </section>
  );
}
