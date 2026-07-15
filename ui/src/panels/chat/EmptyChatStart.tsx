import type { CSSProperties } from "react";

import type { ChatAgent } from "@/panels/chat/constants";
import { greetingFor } from "@/panels/chat/formatting";
import { MeshCanvas } from "@/panels/chat/MeshCanvas";

interface EmptyChatStartProps {
  activeAgent: ChatAgent;
  userName: string;
}

export function EmptyChatStart({
  activeAgent,
  userName,
}: EmptyChatStartProps): JSX.Element {
  return (
    <div className="chat-empty-v3">
      <MeshCanvas active />
      <div className="chat-empty-v3__content">
        <h1>{greetingFor(userName)}</h1>
        <div className="agent-switcher" aria-label="Assistant">
          <div className="agent-switcher__profile">
            <strong style={{ color: activeAgent.color } as CSSProperties}>{activeAgent.name}</strong>
            <span>{activeAgent.role}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export { type EmptyChatStartProps };
