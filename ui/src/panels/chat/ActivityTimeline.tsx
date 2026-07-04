import { Fragment, useState, type CSSProperties, type ReactNode } from "react";

import type { ChatMessage } from "@/api/types";
import type { ChatAgent } from "@/panels/chat/constants";
import { buildTimelineNodes } from "@/panels/chat/activityUtils";
import { Icon } from "@/panels/chat/icons";
import type { ActivityNode } from "@/panels/chat/types";
import type { NormalizedTurn } from "@/panels/chatTurn";

interface ActivityTimelineProps {
  messages: ChatMessage[];
  live: NormalizedTurn;
  activeAgent: ChatAgent;
  onOpenRun: (runId: string) => void;
}

interface ActivityNodeRowProps {
  node: ActivityNode;
  depth: number;
  index: number;
  total: number;
  expanded: Record<string, boolean>;
  onToggle: (key: string) => void;
  onOpenRun: (runId: string) => void;
}

function ActivityNodeRow({
  node,
  depth,
  index,
  total,
  expanded,
  onToggle,
  onOpenRun,
}: ActivityNodeRowProps): ReactNode {
  const hasChildren = Boolean(node.children?.length);
  const isExpanded = expanded[node.key] ?? depth < 1;

  return (
    <Fragment key={node.key}>
      <button
        type="button"
        className={`activity-row ${hasChildren ? "activity-row--expandable" : ""}`}
        style={{ "--activity-color": node.tone, "--depth": depth } as CSSProperties}
        aria-expanded={hasChildren ? isExpanded : undefined}
        onClick={() => {
          if (hasChildren) onToggle(node.key);
          if (node.runId) onOpenRun(node.runId);
        }}
      >
        <span className="activity-row__rail">
          <span />
          {(index < total - 1 || (hasChildren && isExpanded)) && <i />}
        </span>
        <span className="activity-row__body">
          <strong>
            {hasChildren && <Icon name={isExpanded ? "chevDown" : "chevRight"} size={12} />}
            {node.label}
          </strong>
          <small>{node.detail}</small>
        </span>
        {node.badge && <span className="activity-row__badge">{node.badge}</span>}
        <time className="activity-row__time">{node.time}</time>
      </button>
      {hasChildren && isExpanded && (
        <div className="activity-row__children">
          {node.children!.map((child, childIndex) => (
            <ActivityNodeRow
              key={child.key}
              node={child}
              depth={depth + 1}
              index={childIndex}
              total={node.children!.length}
              expanded={expanded}
              onToggle={onToggle}
              onOpenRun={onOpenRun}
            />
          ))}
        </div>
      )}
    </Fragment>
  );
}

export function ActivityTimeline({ messages, live, activeAgent, onOpenRun }: ActivityTimelineProps): JSX.Element {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({ live: true });
  const nodes = buildTimelineNodes({
    messages,
    live,
    activeAgentColor: activeAgent.color,
    activeAgentName: activeAgent.name,
  });

  const toggle = (key: string) => {
    setExpanded((current) => ({ ...current, [key]: !current[key] }));
  };

  return (
    <div className="activity-timeline">
      {nodes.map((node, index) => (
        <ActivityNodeRow
          key={node.key}
          node={node}
          depth={0}
          index={index}
          total={nodes.length}
          expanded={expanded}
          onToggle={toggle}
          onOpenRun={onOpenRun}
        />
      ))}
    </div>
  );
}

export { type ActivityTimelineProps };
