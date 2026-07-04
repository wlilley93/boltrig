import type { CSSProperties } from "react";

import type { ChatAgent } from "@/panels/chat/constants";

interface AgentAvatarProps {
  agent: ChatAgent;
  size?: number;
  status?: boolean;
}

export function AgentAvatar({ agent, size = 32, status = true }: AgentAvatarProps): JSX.Element {
  return (
    <span
      className="agent-avatar"
      style={{ "--agent-color": agent.color, width: size, height: size } as CSSProperties}
      aria-hidden="true"
    >
      {agent.initials}
      {status && <span className={`agent-avatar__status agent-avatar__status--${agent.status}`} />}
    </span>
  );
}

export { type AgentAvatarProps };
export { statusColor } from "@/panels/chat/formatting";
