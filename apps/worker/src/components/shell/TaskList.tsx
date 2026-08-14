import { useState } from "react";
import type { ConversationSummary } from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import { archiveLocalConversation, localThreadId } from "../../localAgentClient";
import { ShellIcon } from "./ShellIcon";
import {
  loadShellPreferences,
  persistShellPreferences,
} from "./shellPreferences";

interface TaskListProps {
  conversations: ConversationSummary[];
  conversationStatus: "loading" | "ready" | "unavailable";
  selectedConversation: string | null;
  workingConversationIds: readonly string[];
  onConversation(id: string): void;
  onConversationArchived?(id: string): void;
  onLoadMore(): void;
  onRetryConversations?(): void;
  hasMoreConversations: boolean;
}

/**
 * The task-list boundary owns presentation-only pin state and conversation-row
 * actions. Browser rows are server summaries; signed desktop rows are local
 * summaries with the same presentation contract.
 */
export function TaskList(props: TaskListProps) {
  const model = useTaskListModel(props);
  const row = (conversation: ConversationSummary) => (
    <ConversationRow key={conversation.id} conversation={conversation} model={model} props={props} />
  );
  return (
    <div className="sessions shell-task-list">
      {model.pinnedConversations.length > 0 && (
        <section aria-labelledby="shell-pinned-tasks" className="shell-task-group">
          <p className="shell-task-group-label" id="shell-pinned-tasks">Pinned</p>
          <div className="shell-task-rows">{model.pinnedConversations.map(row)}</div>
        </section>
      )}
      <section aria-labelledby="shell-recent-tasks" className="shell-task-group">
        <p className="shell-task-group-label" id="shell-recent-tasks">Recents</p>
        <div className="shell-task-rows">
          <ConversationListState model={model} props={props} />
          {model.recentConversations.map(row)}
          {model.conversationActionError && (
            <p className="session-error" role="alert">{model.conversationActionError}</p>
          )}
          {props.conversationStatus === "ready" && props.hasMoreConversations && (
            <button className="secondary-button" onClick={props.onLoadMore} type="button">
              Load more conversations
            </button>
          )}
        </div>
      </section>
    </div>
  );
}

function useTaskListModel(props: TaskListProps) {
  const [conversationAction, setConversationAction] = useState<string | null>(null);
  const [conversationActionError, setConversationActionError] = useState("");
  const [pinnedConversationIds, setPinnedConversationIds] = useState<string[]>(
    () => loadShellPreferences().pinnedConversationIds,
  );

  // Recovery lives in Settings > Archived chats. Keep closed rows outside both
  // groups rather than allowing a second lifecycle inside the navigation rail.
  const openConversations = props.conversations.filter(
    (conversation) => conversation.status !== "closed",
  );
  const pinnedConversations = openConversations.filter(
    (conversation) => pinnedConversationIds.includes(conversation.id),
  );
  const recentConversations = openConversations.filter(
    (conversation) => !pinnedConversationIds.includes(conversation.id),
  );
  const onlyClosedConversations = props.conversations.length > 0
    && openConversations.length === 0;

  function togglePinnedConversation(id: string) {
    setPinnedConversationIds((current) => {
      const next = current.includes(id)
        ? current.filter((conversationId) => conversationId !== id)
        : [...current, id];
      return persistShellPreferences({ pinnedConversationIds: next }).pinnedConversationIds;
    });
  }

  async function archiveConversation(id: string) {
    setConversationAction(id);
    setConversationActionError("");
    try {
      if (localThreadId(id)) {
        if (!archiveLocalConversation(id)) {
          setConversationActionError("The local task could not be archived.");
          return;
        }
        props.onConversationArchived?.(id);
        return;
      }
      const result = await client.deleteMyConversation(id);
      if (result.status !== "ok") {
        setConversationActionError(result.reason ?? "The conversation could not be archived.");
        return;
      }
      props.onConversationArchived?.(id);
    } catch {
      setConversationActionError("The conversation could not be archived. It is safe to retry.");
    } finally {
      setConversationAction(null);
    }
  }

  return {
    archiveConversation,
    conversationAction,
    conversationActionError,
    onlyClosedConversations,
    openConversations,
    pinnedConversationIds,
    pinnedConversations,
    recentConversations,
    togglePinnedConversation,
  };
}

type TaskListModel = ReturnType<typeof useTaskListModel>;

function ConversationRow({ conversation, model, props }: {
  conversation: ConversationSummary;
  model: TaskListModel;
  props: TaskListProps;
}) {
  const title = conversation.title || "Untitled task";
  const isPinned = model.pinnedConversationIds.includes(conversation.id);
  const isSelected = props.selectedConversation === conversation.id;
  return <div className={`session-row${isSelected ? " active" : ""}${isPinned ? " pinned" : ""}`}
    data-conversation-id={conversation.id}>
    <button aria-current={isSelected ? "page" : undefined} className="session-main"
      onClick={() => props.onConversation(conversation.id)} type="button">
      <span className="session-title"><span>{title}</span>
        {(conversation.working === true
          || props.workingConversationIds.includes(conversation.id)) && (
          <span aria-label="Working on this chat" className="session-working-indicator"
            role="status" title="Working on this chat" />
        )}
      </span>
    </button>
    <div className="session-actions" aria-label={`Actions for ${title}`}>
      <button aria-label={isPinned ? `Unpin ${title}` : `Pin ${title}`}
        className="session-action session-pin-action" onClick={(event) => {
          event.stopPropagation(); model.togglePinnedConversation(conversation.id);
        }} title={isPinned ? "Unpin conversation" : "Pin conversation"} type="button">
        <ShellIcon name="pin" size={13} />
      </button>
      <button aria-label={`Archive ${title}`} className="session-action"
        disabled={model.conversationAction === conversation.id} onClick={(event) => {
          event.stopPropagation(); void model.archiveConversation(conversation.id);
        }} title="Archive conversation" type="button">
        <ShellIcon name="archive" size={13} />
      </button>
    </div>
  </div>;
}

function ConversationListState({ model, props }: { model: TaskListModel; props: TaskListProps }) {
  if (props.conversationStatus === "loading") return (
    <p className="muted small" role="status">
      {props.conversations.length > 0 ? "Refreshing conversations…" : "Loading conversations…"}
    </p>
  );
  if (props.conversationStatus === "unavailable") return <div className="session-error" role="alert">
    <p>{props.conversations.length > 0
      ? "Conversation refresh is unavailable. Previously loaded conversations may be stale."
      : "Conversations are unavailable."}</p>
    {props.onRetryConversations && <button className="secondary-button"
      onClick={props.onRetryConversations} type="button">Retry conversations</button>}
  </div>;
  if (model.openConversations.length === 0) return <p className="muted small">
    {model.onlyClosedConversations ? "No recent conversations" : "No conversations yet"}
  </p>;
  return null;
}
