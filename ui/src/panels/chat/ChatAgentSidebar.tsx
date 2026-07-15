import { useState } from "react";

import type { ConversationSearchResult } from "@/api/types";
import { Skeleton } from "@/panels/uxFlow";
import { AgentAvatar } from "@/panels/chat/AgentAvatar";
import type { ChatAgent } from "@/panels/chat/constants";
import { ConversationRow } from "@/panels/chat/ConversationRow";
import { Icon } from "@/panels/chat/icons";
import type { RailState } from "@/panels/chat/types";

interface ChatAgentSidebarProps {
  open: boolean;
  agents: ChatAgent[];
  activeAgent: ChatAgent;
  railItems: ConversationSearchResult[];
  railTerm: string;
  railState: RailState;
  onNew: () => void;
  onSelectAgent: (agent: ChatAgent) => void;
  onSelectConversation: (id: string) => void;
  onDeleted: (id: string) => void;
  onRenamed: () => void;
  loadMore: () => void;
  onRailTerm: (term: string) => void;
}

export function ChatAgentSidebar({
  open,
  agents,
  activeAgent,
  railItems,
  railTerm,
  railState,
  onNew,
  onSelectAgent,
  onSelectConversation,
  onDeleted,
  onRenamed,
  loadMore,
  onRailTerm,
}: ChatAgentSidebarProps): JSX.Element | null {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({ bolt: true });
  const [searchOpen, setSearchOpen] = useState(false);
  if (!open) return null;

  return (
    <aside className="chat-agent-rail" aria-label="Conversations">
      <div className="chat-agent-rail__head">
        <strong>Chat</strong>
        <div className="chat-agent-rail__tools">
          <button
            className={`icon-btn ${searchOpen ? "icon-btn--active" : ""}`}
            title="Search conversations"
            type="button"
            aria-pressed={searchOpen}
            onClick={() => setSearchOpen((v) => !v)}
          >
            <Icon name="search" size={15} />
          </button>
          <button className="icon-btn" title="New chat" type="button" onClick={onNew}>
            <Icon name="plus" size={15} />
          </button>
        </div>
      </div>
      {searchOpen && (
        <div className="chat-agent-rail__search">
          <input
            type="text"
            value={railTerm}
            placeholder="Search conversations..."
            aria-label="Search conversations"
            onChange={(e) => onRailTerm(e.target.value)}
          />
        </div>
      )}
      <div className="chat-agent-list">
        {agents.map((agent) => (
          <AgentGroup
            key={agent.id}
            agent={agent}
            activeAgent={activeAgent}
            expanded={expanded}
            setExpanded={setExpanded}
            railState={railState}
            railItems={railItems}
            railTerm={railTerm}
            onNew={onNew}
            onSelectAgent={onSelectAgent}
            onSelectConversation={onSelectConversation}
            onDeleted={onDeleted}
            onRenamed={onRenamed}
            loadMore={loadMore}
          />
        ))}
      </div>
    </aside>
  );
}

interface AgentGroupProps {
  agent: ChatAgent;
  activeAgent: ChatAgent;
  expanded: Record<string, boolean>;
  setExpanded: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  railState: RailState;
  railItems: ConversationSearchResult[];
  railTerm: string;
  onNew: () => void;
  onSelectAgent: (agent: ChatAgent) => void;
  onSelectConversation: (id: string) => void;
  onDeleted: (id: string) => void;
  onRenamed: () => void;
  loadMore: () => void;
}

function AgentGroup({
  agent,
  activeAgent,
  expanded,
  setExpanded,
  railState,
  railItems,
  railTerm,
  onNew,
  onSelectAgent,
  onSelectConversation,
  onDeleted,
  onRenamed,
  loadMore,
}: AgentGroupProps): JSX.Element {
  const isOpen = Boolean(expanded[agent.id]);
  const isActive = agent.id === activeAgent.id;

  return (
    <div className="chat-agent-group">
      <button
        type="button"
        className={`chat-agent-row ${isActive ? "chat-agent-row--active" : ""}`}
        onClick={() => onSelectAgent(agent)}
      >
        <span
          className={`chat-agent-row__chev ${isOpen ? "chat-agent-row__chev--open" : ""}`}
          onClick={(e) => {
            e.stopPropagation();
            setExpanded((prev) => ({ ...prev, [agent.id]: !isOpen }));
          }}
        >
          <Icon name="chevRight" size={13} />
        </span>
        <AgentAvatar agent={agent} status={false} />
        <span className="chat-agent-row__copy">
          <strong>{agent.name}</strong>
          <span>{agent.snippet}</span>
        </span>
        {agent.unread && <span className="chat-agent-row__badge">{agent.unread}</span>}
      </button>
      {isOpen && (
        <div className="chat-agent-history">
          {agent.id === "bolt" ? (
            <BoltHistory
              railState={railState}
              railItems={railItems}
              railTerm={railTerm}
              onSelectConversation={onSelectConversation}
              onDeleted={onDeleted}
              onRenamed={onRenamed}
              loadMore={loadMore}
              onNew={onNew}
            />
          ) : (
            <NonBoltHistory agent={agent} onSelectAgent={onSelectAgent} onNew={onNew} />
          )}
        </div>
      )}
    </div>
  );
}

interface NonBoltHistoryProps {
  agent: ChatAgent;
  onSelectAgent: (agent: ChatAgent) => void;
  onNew: () => void;
}

function NonBoltHistory({ agent, onSelectAgent, onNew }: NonBoltHistoryProps): JSX.Element {
  return (
    <>
      {agent.history.map((h) => (
        <button
          type="button"
          className="chat-agent-history__item"
          key={h.id}
          onClick={() => onSelectAgent(agent)}
        >
          <span>{h.title}</span>
          <time>{h.time}</time>
        </button>
      ))}
      <button className="chat-agent-history__new" type="button" onClick={onNew}>
        <Icon name="plus" size={12} />
        New chat
      </button>
    </>
  );
}

interface BoltHistoryProps {
  railState: RailState;
  railItems: ConversationSearchResult[];
  railTerm: string;
  onSelectConversation: (id: string) => void;
  onDeleted: (id: string) => void;
  onRenamed: () => void;
  loadMore: () => void;
  onNew: () => void;
}

function BoltHistory({
  railState,
  railItems,
  railTerm,
  onSelectConversation,
  onDeleted,
  onRenamed,
  loadMore,
  onNew,
}: BoltHistoryProps): JSX.Element {
  return (
    <>
      {railState.loading && railItems.length === 0 && <Skeleton variant="rows" count={3} />}
      {!railState.loading && railItems.length === 0 && (
        <p className="chat-agent-history__empty">
          {railState.mode === "search" ? "No matches" : "No conversations yet."}
        </p>
      )}
      {railItems.map((c) => (
        <ConversationRow
          key={c.id}
          conversation={c}
          active={false}
          highlight={railTerm}
          onSelect={() => onSelectConversation(c.id)}
          onDeleted={() => onDeleted(c.id)}
          onRenamed={onRenamed}
        />
      ))}
      {railState.nextOffset !== null && (
        <button
          type="button"
          className="chat-agent-history__more"
          disabled={railState.loadingMore}
          onClick={loadMore}
        >
          {railState.loadingMore ? "Loading..." : "Load more"}
        </button>
      )}
      <button className="chat-agent-history__new" type="button" onClick={onNew}>
        <Icon name="plus" size={12} />
        New chat
      </button>
    </>
  );
}

export { type ChatAgentSidebarProps };
