import type { CSSProperties } from "react";

import type { ChatAgent } from "@/panels/chat/constants";
import { greetingFor } from "@/panels/chat/formatting";
import { Icon } from "@/panels/chat/icons";
import { MeshCanvas } from "@/panels/chat/MeshCanvas";

interface EmptyChatStartProps {
  activeAgent: ChatAgent;
  onPrev: () => void;
  onNext: () => void;
  switchDir: "left" | "right" | "";
  switchCount: number;
  userName: string;
}

export function EmptyChatStart({
  activeAgent,
  onPrev,
  onNext,
  switchDir,
  switchCount,
  userName,
}: EmptyChatStartProps): JSX.Element {
  const anim = switchDir ? `agent-switcher__profile--${switchDir}-${switchCount % 2 ? "a" : "b"}` : "";
  return (
    <div className="chat-empty-v3">
      <MeshCanvas active />
      <div className="chat-empty-v3__content">
        <h1>{greetingFor(userName)}</h1>
        <div className="agent-switcher" aria-label="Choose agent">
          <button className="agent-switcher__arrow" type="button" onClick={onPrev} aria-label="Previous agent">
            <Icon name="chevLeft" size={18} />
          </button>
          <div className={`agent-switcher__profile ${anim}`}>
            <strong style={{ color: activeAgent.color } as CSSProperties}>{activeAgent.name}</strong>
            <span>{activeAgent.role}</span>
          </div>
          <button className="agent-switcher__arrow" type="button" onClick={onNext} aria-label="Next agent">
            <Icon name="chevRight" size={18} />
          </button>
        </div>
      </div>
    </div>
  );
}

export { type EmptyChatStartProps };
