import type { CSSProperties } from "react";

import { Familiar, useFamiliarAvailable } from "@/familiar/Familiar";
import type { RunFacts } from "@/familiar/phenotype";
import type { ChatAgent } from "@/panels/chat/constants";

interface AgentAvatarProps {
  agent: ChatAgent;
  size?: number;
  status?: boolean;
  /** live run facts, when the caller has them; drives the familiar's mood */
  run?: RunFacts;
  /** 0..1 voice level during a call */
  voice?: number;
}

/**
 * THE ONE PLACE AN AGENT BECOMES A PICTURE.
 *
 * This component was already the single seam: the fleet bar, the hover card, the activity
 * timeline, message bubbles, the sub-run panel and the agent sidebar all render an agent
 * through it. Putting the familiar HERE rather than in each of those is the whole integration
 * - six surfaces get it at once, they cannot disagree about what an agent looks like, and a
 * seventh surface added tomorrow inherits it without anyone remembering to wire it up.
 *
 * The initials do not go away. They are the fallback for a browser without WebGL2 and for the
 * moment before the shader links, and the status dot stays on top in both cases, because the
 * dot is the accessible, unambiguous statement of state and the familiar is the glanceable
 * one. Two channels carrying the same fact is not duplication here; it is the reason this can
 * ship without an accessibility regression.
 */
export function AgentAvatar({ agent, size = 32, status = true, run, voice }: AgentAvatarProps): JSX.Element {
  const canRender = useFamiliarAvailable();
  const runFacts: RunFacts | undefined =
    run ??
    (agent.status === "offline"
      ? { status: "offline" }
      : agent.status === "active"
        ? { status: "running" }
        : { status: "idle" });

  return (
    <span
      className={`agent-avatar${canRender ? " agent-avatar--familiar" : ""}`}
      style={{ "--agent-color": agent.color, width: size, height: size } as CSSProperties}
      aria-hidden="true"
    >
      {canRender ? (
        <Familiar agent={{ id: agent.id, role: agent.role }} size={size} run={runFacts} voice={voice} />
      ) : (
        agent.initials
      )}
      {status && <span className={`agent-avatar__status agent-avatar__status--${agent.status}`} />}
    </span>
  );
}

export { type AgentAvatarProps };
export { statusColor } from "@/panels/chat/formatting";
