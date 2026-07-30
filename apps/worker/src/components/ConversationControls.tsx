import { useEffect, useState } from "react";

import { client } from "../client";

interface ConversationControlsProps {
  conversationId: string;
  title: string;
  status: string;
  lastAssistantMessageId?: string | null;
  onChanged?(): void;
  onDeleted?(): void;
}

export function ConversationControls({
  conversationId,
  title,
  status,
  lastAssistantMessageId,
  onChanged,
  onDeleted,
}: ConversationControlsProps) {
  const [draft, setDraft] = useState(title);
  const [message, setMessage] = useState("");
  const [messageIsError, setMessageIsError] = useState(false);
  const [deleteArmed, setDeleteArmed] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => setDraft(title), [title]);

  async function rename() {
    const next = draft.trim();
    if (!next || next.length > 120) {
      setMessage("Titles must be between 1 and 120 characters.");
      setMessageIsError(true);
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const result = await client.renameConversation(conversationId, next);
      setMessageIsError(result.status !== "ok");
      setMessage(result.status === "ok" ? "Conversation renamed." : result.reason ?? result.status);
      if (result.status === "ok") onChanged?.();
    } catch {
      setMessageIsError(true);
      setMessage("The conversation could not be renamed. It is safe to retry.");
    } finally {
      setBusy(false);
    }
  }

  async function regenerate() {
    if (!lastAssistantMessageId) return;
    setBusy(true);
    setMessage("");
    try {
      const result = await client.regenerateMessage(conversationId, lastAssistantMessageId);
      setMessageIsError(result.status !== "ok");
      setMessage(
        result.status === "ok"
          ? "A new response was appended; the previous response remains in history."
          : result.reason ?? result.status,
      );
      if (result.status === "ok") onChanged?.();
    } catch {
      setMessageIsError(true);
      setMessage("The response could not be regenerated. It is safe to retry.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!deleteArmed) {
      setDeleteArmed(true);
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const result = await client.deleteMyConversation(conversationId);
      setMessageIsError(result.status !== "ok");
      setMessage(result.status === "ok" ? "Conversation closed." : result.reason ?? result.status);
      if (result.status === "ok") onDeleted?.();
    } catch {
      setMessageIsError(true);
      setMessage("The conversation could not be closed. It is safe to retry.");
    } finally {
      setBusy(false);
    }
  }

  async function restore() {
    setBusy(true);
    setMessage("");
    try {
      const result = await client.restoreMyConversation(conversationId);
      setMessageIsError(result.status !== "ok");
      setMessage(
        result.status === "ok"
          ? "Conversation restored."
          : result.reason ?? result.status,
      );
      if (result.status === "ok") onChanged?.();
    } catch {
      setMessageIsError(true);
      setMessage("The conversation could not be restored. It is safe to retry.");
    } finally {
      setBusy(false);
    }
  }

  if (status === "closed") {
    return (
      <section className="settings-card" aria-label="Closed conversation controls">
        <p className="eyebrow">Closed conversation</p>
        <h3>{title || "Untitled task"}</h3>
        <p className="muted small">
          This transcript is read-only during its retention grace window. Restore it
          before adding a turn or regenerating a reply.
        </p>
        <button
          className="primary-button"
          disabled={busy}
          onClick={() => void restore()}
        >
          {busy ? "Restoring…" : "Restore conversation"}
        </button>
        {message && <p className="notice" role={messageIsError ? "alert" : "status"}>{message}</p>}
      </section>
    );
  }

  return (
    <section className="settings-card" aria-label="Conversation controls">
      <p className="eyebrow">Conversation</p>
      <label>
        <span className="muted small">Title</span>
        <input
          className="field-control"
          aria-label="Conversation title"
          maxLength={120}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
      </label>
      <div className="button-row">
        {lastAssistantMessageId && (
          <button className="secondary-button" disabled={busy} onClick={() => void regenerate()}>
            Regenerate last response
          </button>
        )}
        <button className="primary-button" disabled={busy} onClick={() => void rename()}>
          Save title
        </button>
      </div>
      <button
        className={deleteArmed ? "danger-button armed" : "danger-button"}
        disabled={busy}
        onClick={() => void remove()}
      >
        {deleteArmed ? "Confirm close conversation" : "Close conversation"}
      </button>
      {message && <p className="notice" role={messageIsError ? "alert" : "status"}>{message}</p>}
    </section>
  );
}
