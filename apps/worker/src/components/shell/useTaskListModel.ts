import { useState, type Dispatch, type SetStateAction } from "react";
import type { ConversationSummary } from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import { archiveLocalConversation, localThreadId } from "../../localAgentClient";
import { notifyWorkerContextChanged } from "../WorkerGlobalContext";
import {
  loadShellOrganizeMode,
  loadShellPreferences,
  persistShellOrganizeMode,
  persistShellPreferences,
  type ShellOrganizeMode,
} from "./shellPreferences";

export interface TaskListModelInput {
  conversations: ConversationSummary[];
  onConversation(id: string): void;
  onConversationArchived?(id: string): void;
  onRetryConversations?(): void;
}

export function useTaskListModel(props: TaskListModelInput) {
  const preferences = useTaskListPreferences();
  const actions = useTaskListActions(props);
  const openConversations = props.conversations.filter((item) => item.status !== "closed");
  const pinnedConversations = openConversations.filter(
    (item) => preferences.pinnedConversationIds.includes(item.id),
  );
  return {
    ...actions,
    ...preferences,
    onlyClosedConversations: props.conversations.length > 0 && openConversations.length === 0,
    openConversations,
    pinnedConversations,
    unpinnedConversations: openConversations.filter(
      (item) => !preferences.pinnedConversationIds.includes(item.id),
    ),
  };
}

function useTaskListPreferences() {
  const [organizeMode, setOrganizeModeState] = useState<ShellOrganizeMode>(loadShellOrganizeMode);
  const [collapsedGroups, setCollapsedGroups] = useState<string[]>([]);
  const [pinnedConversationIds, setPinnedConversationIds] = useState<string[]>(
    () => loadShellPreferences().pinnedConversationIds,
  );
  const setOrganizeMode = (mode: ShellOrganizeMode) => {
    setOrganizeModeState(mode);
    persistShellOrganizeMode(mode);
  };
  const toggleCollapsed = (id: string) => setCollapsedGroups((current) => (
    current.includes(id) ? current.filter((item) => item !== id) : [...current, id]
  ));
  const togglePinnedConversation = (id: string) => setPinnedConversationIds((current) => {
    const next = current.includes(id)
      ? current.filter((conversationId) => conversationId !== id)
      : [...current, id];
    return persistShellPreferences({ pinnedConversationIds: next }).pinnedConversationIds;
  });
  return {
    collapsedGroups,
    organizeMode,
    pinnedConversationIds,
    setOrganizeMode,
    toggleCollapsed,
    togglePinnedConversation,
  };
}

function useTaskListActions(props: TaskListModelInput) {
  const [conversationAction, setConversationAction] = useState<string | null>(null);
  const [conversationActionError, setConversationActionError] = useState("");
  return {
    archiveConversation: (id: string) => performArchive(
      id, props, setConversationAction, setConversationActionError,
    ),
    conversationAction,
    conversationActionError,
    moveConversation: (conversation: ConversationSummary, workspaceId: string | null) => (
      performMove(conversation, workspaceId, props, setConversationAction, setConversationActionError)
    ),
    newConversation: (workspaceId: string | null, begin: () => void) => (
      openProject(workspaceId, setConversationActionError).then((ready) => { if (ready) begin(); })
    ),
    openConversation: (conversation: ConversationSummary) => openProject(
      conversation.workspace_id ?? null,
      setConversationActionError,
    ).then((ready) => { if (ready) props.onConversation(conversation.id); }),
  };
}

async function openProject(
  workspaceId: string | null,
  setError: Dispatch<SetStateAction<string>>,
): Promise<boolean> {
  setError("");
  if (!workspaceId) return true;
  try {
    const result = await client.switchActiveContext(workspaceId);
    if (result.status !== "ok") {
      setError(result.reason ?? "That project is not available.");
      return false;
    }
    notifyWorkerContextChanged();
    return true;
  } catch {
    setError("The project context could not be opened. It is safe to retry.");
    return false;
  }
}

async function performMove(
  conversation: ConversationSummary,
  workspaceId: string | null,
  props: TaskListModelInput,
  setAction: Dispatch<SetStateAction<string | null>>,
  setError: Dispatch<SetStateAction<string>>,
) {
  if (localThreadId(conversation.id)) {
    setError("Local desktop chats cannot be moved into a cloud project.");
    return;
  }
  setAction(conversation.id);
  setError("");
  try {
    const result = await client.moveConversationProject(
      conversation.id, workspaceId, conversation.workspace_id ?? null,
    );
    if (result.status !== "ok") setError(result.reason ?? "The chat could not be moved.");
    else props.onRetryConversations?.();
  } catch {
    setError("The chat could not be moved. It is safe to retry.");
  } finally {
    setAction(null);
  }
}

async function performArchive(
  id: string,
  props: TaskListModelInput,
  setAction: Dispatch<SetStateAction<string | null>>,
  setError: Dispatch<SetStateAction<string>>,
) {
  setAction(id);
  setError("");
  try {
    if (localThreadId(id)) {
      if (!archiveLocalConversation(id)) setError("The local task could not be archived.");
      else props.onConversationArchived?.(id);
      return;
    }
    const result = await client.deleteMyConversation(id);
    if (result.status !== "ok") {
      setError(result.reason ?? "The conversation could not be archived.");
      return;
    }
    props.onConversationArchived?.(id);
  } catch {
    setError("The conversation could not be archived. It is safe to retry.");
  } finally {
    setAction(null);
  }
}
