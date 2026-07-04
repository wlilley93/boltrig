import { useRef, useState } from "react";

import { api } from "@/api/client";
import type { ConversationSearchResult } from "@/api/types";
import { ArmConfirm } from "@/panels/uxFlow";
import { Highlight } from "@/panels/chat/Highlight";
import { whenText } from "@/panels/chat/formatting";

interface ConversationRowProps {
  conversation: ConversationSearchResult;
  active: boolean;
  highlight?: string;
  onSelect: () => void;
  onDeleted: () => void;
  onRenamed: () => void;
}

interface RenameEditorProps {
  initialTitle: string;
  onCommit: (next: string) => void;
  onCancel: () => void;
}

function RenameEditor({ initialTitle, onCommit, onCancel }: RenameEditorProps): JSX.Element {
  const [draft, setDraft] = useState(initialTitle);
  const cancelledRef = useRef(false);

  return (
    <input
      className="chat__search"
      aria-label="Conversation title"
      value={draft}
      autoFocus
      maxLength={120}
      onChange={(e) => setDraft(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.currentTarget.blur();
        } else if (e.key === "Escape") {
          e.stopPropagation();
          cancelledRef.current = true;
          onCancel();
        }
      }}
      onBlur={() => {
        if (cancelledRef.current) {
          cancelledRef.current = false;
          return;
        }
        onCommit(draft.trim());
      }}
    />
  );
}

interface ConversationContentProps {
  conversation: ConversationSearchResult;
  active: boolean;
  highlight: string;
  onSelect: () => void;
}

function ConversationContent({ conversation, active, highlight, onSelect }: ConversationContentProps): JSX.Element {
  const title = conversation.title || "(untitled)";
  const snippet = conversation.snippet;
  return (
    <button className={`conv-item ${active ? "conv-item--active" : ""}`} onClick={onSelect}>
      <span className="conv-item__title">
        <Highlight text={title} term={highlight} />
      </span>
      {snippet && (
        <span className="conv-item__snippet">
          <Highlight text={snippet} term={highlight} />
        </span>
      )}
      <span className="conv-item__meta">
        <span className="muted" title={conversation.updated_at}>
          {whenText(conversation.updated_at)}
        </span>
      </span>
    </button>
  );
}

export function ConversationRow({
  conversation,
  active,
  highlight = "",
  onSelect,
  onDeleted,
  onRenamed,
}: ConversationRowProps): JSX.Element {
  const title = conversation.title || "(untitled)";
  const [renaming, setRenaming] = useState(false);
  const [renameError, setRenameError] = useState<string | null>(null);

  async function deleteConversation() {
    const res = await api.deleteMyConversation(conversation.id);
    if (res.status !== "ok") throw new Error(res.reason ?? `Delete failed: ${res.status}`);
    onDeleted();
  }

  async function commitRename(next: string) {
    if (!next || next === (conversation.title ?? "")) {
      setRenaming(false);
      return;
    }
    const res = await api.renameConversation(conversation.id, next);
    if (res.status !== "ok") {
      setRenameError(res.reason ?? `Rename failed: ${res.status}`);
      return;
    }
    setRenaming(false);
    onRenamed();
  }

  return (
    <li className="conv-row">
      {renaming ? (
        <RenameEditor
          initialTitle={conversation.title || ""}
          onCommit={commitRename}
          onCancel={() => setRenaming(false)}
        />
      ) : (
        <ConversationContent
          conversation={conversation}
          active={active}
          highlight={highlight}
          onSelect={onSelect}
        />
      )}
      <div className="conv-row__actions">
        {!renaming && (
          <button type="button" className="btn" onClick={() => setRenaming(true)}>
            Rename
          </button>
        )}
        <ArmConfirm
          label="Delete"
          armLabel={<>Delete <strong>{title}</strong>? The audit log is kept.</>}
          confirmLabel="Confirm delete"
          busyLabel="Deleting"
          tone="danger"
          onConfirm={deleteConversation}
        />
      </div>
      {renameError && (
        <p className="error" role="alert">
          {renameError}
        </p>
      )}
    </li>
  );
}

export { type ConversationRowProps };
