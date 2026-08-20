import { useMemo } from "react";
import type {
  ConversationSummary,
  NamedAgentView,
} from "@wlilley93/boltrig-web-sdk";

import { localThreadId } from "../../localAgentClient";
import { setPendingChatAgent } from "../chat/pendingChatTarget";
import { ShellIcon } from "./ShellIcon";
import type { ShellOrganizeMode } from "./shellPreferences";
import { useDirectoryMetadata } from "./useDirectoryMetadata";
import { useTaskListModel } from "./useTaskListModel";

type OrganizeMode = ShellOrganizeMode;

interface TaskListProps {
  conversations: ConversationSummary[];
  conversationStatus: "loading" | "ready" | "unavailable";
  selectedConversation: string | null;
  workingConversationIds: readonly string[];
  onConversation(id: string): void;
  onNewConversation(): void;
  onConversationArchived?(id: string): void;
  onLoadMore(): void;
  onRetryConversations?(): void;
  hasMoreConversations: boolean;
}

/**
 * Projects and agent piles are projections over the same durable conversations.
 * Dragging changes only Workspace membership; switching agent is admitted by the
 * composer on the next idle turn and never rewrites a historical message.
 */
export function TaskList(props: TaskListProps) {
  const model = useTaskListModel(props);
  const viewProps = { ...props, ...useDirectoryMetadata() };
  return (
    <div className="sessions shell-task-list">
      <TaskOrganizer mode={model.organizeMode} onMode={model.setOrganizeMode} />
      {model.pinnedConversations.length > 0 && (
        <TaskSection label="Pinned">
          {model.pinnedConversations.map((conversation) => (
            <ConversationRow key={conversation.id} conversation={conversation}
              model={model} props={viewProps} />
          ))}
        </TaskSection>
      )}
      {model.organizeMode === "project" && (
        <ProjectProjection model={model} props={viewProps} />
      )}
      {model.organizeMode === "agent" && (
        <AgentProjection model={model} props={viewProps} />
      )}
      {model.organizeMode === "list" && (
        <TaskSection label="Chats">
          <ConversationListState model={model} props={viewProps} />
          {model.unpinnedConversations.map((conversation) => (
            <ConversationRow key={conversation.id} conversation={conversation}
              model={model} props={viewProps} />
          ))}
        </TaskSection>
      )}
      {model.conversationActionError && (
        <p className="session-error" role="alert">{model.conversationActionError}</p>
      )}
      {props.conversationStatus === "ready" && props.hasMoreConversations && (
        <button className="secondary-button" onClick={props.onLoadMore} type="button">
          Load more conversations
        </button>
      )}
    </div>
  );
}

type TaskListModel = ReturnType<typeof useTaskListModel>;
type TaskListViewProps = TaskListProps & ReturnType<typeof useDirectoryMetadata>;

function TaskOrganizer({ mode, onMode }: {
  mode: OrganizeMode; onMode(mode: OrganizeMode): void;
}) {
  const options: Array<[OrganizeMode, string]> = [
    ["project", "By project"],
    ["agent", "By agent"],
    ["list", "In one list"],
  ];
  return (
    <div className="shell-task-organizer">
      <span>Chats</span>
      <details>
        <summary aria-label="Organize sidebar" title="Organize sidebar">•••</summary>
        <div aria-label="Organize sidebar" className="shell-organize-menu" role="radiogroup">
          <p>Organize sidebar</p>
          {options.map(([value, label]) => (
            <button aria-checked={mode === value} key={value}
              onClick={() => onMode(value)} role="radio" type="button">
              <span>{mode === value ? "✓" : ""}</span>{label}
            </button>
          ))}
          <p className="shell-organize-sort">Sorted by last updated</p>
        </div>
      </details>
    </div>
  );
}

function ProjectProjection({ model, props }: { model: TaskListModel; props: TaskListViewProps }) {
  const projects = useMemo(() => [...props.projects].sort((a, b) => a.name.localeCompare(b.name)),
    [props.projects]);
  const knownProjects = new Set(projects.map((project) => project.id));
  const unfiled = model.unpinnedConversations.filter(
    (item) => !item.workspace_id || !knownProjects.has(item.workspace_id),
  );
  return <>
    <TaskSection label="Projects">
      {projects.map((project) => (
        <ConversationGroup
          key={project.id}
          groupId={`project:${project.id}`}
          label={project.name}
          conversations={model.unpinnedConversations.filter(
            (item) => item.workspace_id === project.id,
          )}
          model={model}
          props={props}
          onAdd={() => void model.newConversation(project.id, props.onNewConversation)}
          onDropConversation={(conversation) => void model.moveConversation(conversation, project.id)}
        />
      ))}
      {projects.length === 0 && <p className="shell-project-empty">No projects</p>}
    </TaskSection>
    <TaskSection label="Recents" onConversationDrop={(id) => {
      const conversation = props.conversations.find((item) => item.id === id);
      if (conversation) void model.moveConversation(conversation, null);
    }}>
      <ConversationListState model={model} props={props} />
      {unfiled.map((conversation) => (
        <ConversationRow key={conversation.id} conversation={conversation}
          model={model} props={props} />
      ))}
    </TaskSection>
  </>;
}

function AgentProjection({ model, props }: { model: TaskListModel; props: TaskListViewProps }) {
  const visibleAgents = props.namedAgents.filter((agent) => agent.enabled);
  const known = new Set(visibleAgents.map((agent) => agent.address));
  const legacy = model.unpinnedConversations.filter(
    (conversation) => !conversation.agent_address || !known.has(conversation.agent_address),
  );
  return <>
    <p className="shell-projection-label">Agents</p>
    {visibleAgents.map((agent) => (
      <AgentGroup key={agent.address} agent={agent}
        conversations={model.unpinnedConversations.filter(
          (conversation) => conversation.agent_address === agent.address,
        )}
        model={model} props={props} />
    ))}
    {legacy.length > 0 && <ConversationGroup groupId="agent:legacy" label="Unassigned"
      conversations={legacy} model={model} props={props} />}
    {visibleAgents.length === 0 && legacy.length === 0 && (
      <ConversationListState model={model} props={props} />
    )}
  </>;
}

function AgentGroup({ agent, conversations, model, props }: {
  agent: NamedAgentView;
  conversations: ConversationSummary[];
  model: TaskListModel;
  props: TaskListViewProps;
}) {
  const groupId = `agent:${agent.address}`;
  const latest = conversations[0];
  const collapsed = model.collapsedGroups.includes(groupId);
  return (
    <section className="shell-conversation-group" data-group-id={groupId}>
      <div className="shell-conversation-group-head">
        <button aria-expanded={!collapsed}
          aria-label={`${collapsed ? "Expand" : "Collapse"} ${agent.name}`}
          className="shell-group-toggle" onClick={() => model.toggleCollapsed(groupId)} type="button">⌄</button>
        <button className="shell-group-title" disabled={!latest}
          onClick={() => latest && void model.openConversation(latest)} type="button">
          <span className="shell-agent-dot" aria-hidden />{agent.name}
        </button>
        <button aria-label={`New chat with ${agent.name}`} className="shell-group-add"
          onClick={() => void model.newConversation(null, () => {
            setPendingChatAgent(agent.address);
            props.onNewConversation();
          })} type="button">＋</button>
      </div>
      {!collapsed && (
        <div className="shell-task-rows">{conversations.map((conversation) => (
          <ConversationRow key={conversation.id} conversation={conversation}
            model={model} props={props} />
        ))}</div>
      )}
    </section>
  );
}

function ConversationGroup({ groupId, label, conversations, model, props, onAdd,
  onDropConversation }: {
  groupId: string;
  label: string;
  conversations: ConversationSummary[];
  model: TaskListModel;
  props: TaskListViewProps;
  onAdd?(): void;
  onDropConversation?(conversation: ConversationSummary): void;
}) {
  const collapsed = model.collapsedGroups.includes(groupId);
  return (
    <section className="shell-conversation-group" data-group-id={groupId}
      onDragOver={(event) => { if (onDropConversation) event.preventDefault(); }}
      onDrop={(event) => {
        const id = event.dataTransfer.getData("text/boltrig-conversation");
        const conversation = props.conversations.find((item) => item.id === id);
        if (conversation && onDropConversation) onDropConversation(conversation);
      }}>
      <div className="shell-conversation-group-head">
        <button aria-expanded={!collapsed} aria-label={`${collapsed ? "Expand" : "Collapse"} ${label}`}
          className="shell-group-toggle" onClick={() => model.toggleCollapsed(groupId)} type="button">⌄</button>
        <span className="shell-group-title">{label}</span>
        {onAdd && <button aria-label={`New chat in ${label}`} className="shell-group-add"
          onClick={onAdd} type="button">＋</button>}
      </div>
      {!collapsed && <div className="shell-task-rows">
        {conversations.map((conversation) => (
          <ConversationRow key={conversation.id} conversation={conversation}
            model={model} props={props} />
        ))}
      </div>}
    </section>
  );
}

function TaskSection({ label, children, onConversationDrop }: {
  label: string; children: React.ReactNode; onConversationDrop?(id: string): void;
}) {
  const labelId = taskSectionLabelId(label);
  return <section aria-labelledby={labelId} className="shell-task-group"
    onDragOver={(event) => { if (onConversationDrop) event.preventDefault(); }}
    onDrop={(event) => onConversationDrop?.(
      event.dataTransfer.getData("text/boltrig-conversation"),
    )}>
    <p className="shell-task-group-label" id={labelId}>{label}</p>
    <div className="shell-task-rows">{children}</div>
  </section>;
}

function taskSectionLabelId(label: string): string {
  if (label === "Pinned") return "shell-pinned-tasks";
  if (label === "Projects") return "shell-projects";
  if (label === "Recents") return "shell-recent-tasks";
  return `shell-${label.toLowerCase().replaceAll(" ", "-")}`;
}

function ConversationRow({ conversation, model, props }: {
  conversation: ConversationSummary;
  model: TaskListModel;
  props: TaskListViewProps;
}) {
  const title = conversation.title || "Untitled task";
  const isPinned = model.pinnedConversationIds.includes(conversation.id);
  const isSelected = props.selectedConversation === conversation.id;
  return <div className={`session-row${isSelected ? " active" : ""}${isPinned ? " pinned" : ""}`}
    data-conversation-id={conversation.id} draggable={!localThreadId(conversation.id)}
    onDragStart={(event) => {
      event.dataTransfer.setData("text/boltrig-conversation", conversation.id);
      event.dataTransfer.effectAllowed = "move";
    }}>
    <button aria-current={isSelected ? "page" : undefined} className="session-main"
      onClick={() => void model.openConversation(conversation)} type="button">
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

function ConversationListState({ model, props }: {
  model: TaskListModel; props: TaskListViewProps;
}) {
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
