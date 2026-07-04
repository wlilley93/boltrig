import { AgentAvatar } from "@/panels/chat/AgentAvatar";
import { CHAT_AGENTS } from "@/panels/chat/constants";
import type { ChatAgent } from "@/panels/chat/constants";
import { statusColor } from "@/panels/chat/formatting";

interface AgentHoverCardProps {
  agent: ChatAgent;
}

function Connector(): JSX.Element {
  return (
    <svg
      className="agent-card__connector"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <line x1="12" y1="0" x2="12" y2="18" />
      <polygon points="12,24 8,18 16,18" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function AgentHoverCard({ agent }: AgentHoverCardProps): JSX.Element {
  const dot = statusColor(agent.status);
  const tier2Children = agent.id === "bolt" ? CHAT_AGENTS.filter((a) => a.tier === 2) : [];

  return (
    <div className="agent-card" role="status">
      <div className="agent-card__head">
        <AgentAvatar agent={agent} size={40} />
        <div>
          <strong>{agent.name}</strong>
          <span>{agent.dept}</span>
        </div>
        <span
          className={`agent-card__status-dot agent-card__status-dot--${agent.status}`}
          style={{
            width: 8,
            height: 8,
            borderRadius: 9999,
            background: dot,
            boxShadow: `0 0 8px ${dot}`,
          }}
          aria-label={agent.status}
        />
      </div>
      <div className="agent-card__org" aria-label="Agent position">
        {agent.tier === 2 && (
          <>
            <div className="agent-card__node agent-card__node--parent">
              <span>B</span>
              <p>Bolt</p>
            </div>
            <Connector />
          </>
        )}
        <div className="agent-card__node agent-card__node--current">
          <span style={{ background: agent.color }}>{agent.initials}</span>
          <p>{agent.name}</p>
        </div>
        {agent.id === "bolt" && tier2Children.length > 0 && (
          <>
            <Connector />
            <div className="agent-card__children">
              {tier2Children.map((child) => (
                <div className="agent-card__node" key={child.id}>
                  <span style={{ background: child.color }}>{child.initials}</span>
                  <p>{child.name.replace("Head of ", "")}</p>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
      <div className="agent-card__meta">
        <code>runtime pi</code>
        <code>glm-5.2</code>
        <code>{agent.tier === 1 ? 12 : 6} skills</code>
      </div>
    </div>
  );
}

export { type AgentHoverCardProps };
