import { useEffect, useRef, useState, type CSSProperties } from "react";

import type { ChatAgent } from "@/panels/chat/constants";
import { Icon } from "@/panels/chat/icons";
import { onFleetFocusRequest, requestComposerFocus } from "@/panels/chat/fleetFocus";
import type { NormalizedTurn } from "@/panels/chatTurn";

interface FleetBarProps {
  live: NormalizedTurn;
  activeAgent: ChatAgent;
  onOpenRun: (runId: string) => void;
}

interface FleetRowData {
  id: string;
  name: string;
  role: string;
  color: string;
  initials: string;
  elapsed: string;
  phase: string;
  cost: string;
  tools: number;
  tier: number;
}

const WINDOW_SIZE = 4;

function buildFleetRows(live: NormalizedTurn, activeAgent: ChatAgent): FleetRowData[] {
  return [
    {
      id: live.runId ?? "bolt",
      name: activeAgent.name,
      role: activeAgent.role,
      color: activeAgent.color,
      initials: activeAgent.initials,
      elapsed: live.ended ? "done" : "00:00",
      phase: live.ended ? "complete" : "coordinating",
      cost: "$0.00",
      tools: live.tools.length,
      tier: activeAgent.tier,
    },
    ...live.subagents.map((sub, i) => ({
      id: sub.childRunId,
      name: `Worker ${i + 1}`,
      role: "ephemeral",
      color: ["#5E69DD", "#3FB984", "#FF7A45"][i % 3],
      initials: String(i + 1),
      elapsed: `00:${String(Math.min(59, 12 + i * 7)).padStart(2, "0")}`,
      phase: "executing",
      cost: "$0.00",
      tools: Math.max(1, sub.skills.length),
      tier: 3,
    })),
  ];
}

interface FleetRowProps {
  row: FleetRowData;
  absoluteIndex: number;
  focusIdx: number;
  setFocusIdx: (idx: number) => void;
  onOpenRun: (runId: string) => void;
}

function FleetRow({ row, absoluteIndex, focusIdx, setFocusIdx, onOpenRun }: FleetRowProps): JSX.Element {
  return (
    <button
      className={`fleet-row ${absoluteIndex === focusIdx ? "fleet-row--focus" : ""}`}
      type="button"
      key={row.id}
      onFocus={() => setFocusIdx(absoluteIndex)}
      onClick={() => row.id && onOpenRun(row.id)}
      style={{
        "--agent-color": row.color,
        gridTemplateColumns: "auto auto 1fr auto auto 56px 56px 70px auto",
      } as CSSProperties}
    >
      <span className="fleet-row__tree">{absoluteIndex === 0 ? " " : "└"}</span>
      <span className="fleet-row__avatar">{row.initials}</span>
      <strong>{row.name}</strong>
      <span
        className="fleet-row__status"
        aria-hidden="true"
        style={{ width: 6, height: 6, borderRadius: 9999, background: row.color }}
      />
      <em>{row.tier === 3 ? "ephemeral" : row.role}</em>
      <span>{row.elapsed}</span>
      <span>{row.cost}</span>
      <span>{row.tools} tool calls</span>
      <span>{row.phase}</span>
    </button>
  );
}

export function FleetBar({ live, activeAgent, onOpenRun }: FleetBarProps): JSX.Element | null {
  const [offset, setOffset] = useState(0);
  const [focusIdx, setFocusIdx] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const rows = buildFleetRows(live, activeAgent);

  // Honour the empty-composer ArrowDown shortcut (sec 18): when the composer
  // asks the fleet to take focus, reset the focus index to the first row and
  // focus the bar so its own Up/Down/Enter/Escape handling takes over.
  useEffect(() => {
    return onFleetFocusRequest(() => {
      setFocusIdx(0);
      setOffset(0);
      rootRef.current?.focus();
    });
  }, []);

  if (!live.runId && live.tools.length === 0 && live.subagents.length === 0) return null;

  const maxOffset = Math.max(0, rows.length - WINDOW_SIZE);
  const clampedOffset = Math.min(offset, maxOffset);
  const visible = rows.slice(clampedOffset, clampedOffset + WINDOW_SIZE);

  const moveFocus = (next: number) => {
    const clamped = Math.max(0, Math.min(rows.length - 1, next));
    setFocusIdx(clamped);
    if (clamped < clampedOffset) setOffset(clamped);
    if (clamped >= clampedOffset + WINDOW_SIZE) setOffset(clamped - WINDOW_SIZE + 1);
  };

  return (
    <div
      className="fleet-bar"
      aria-label="Live fleet"
      tabIndex={0}
      ref={rootRef}
      onKeyDown={(e) => {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          moveFocus(focusIdx + 1);
        } else if (e.key === "ArrowUp") {
          e.preventDefault();
          moveFocus(focusIdx - 1);
        } else if (e.key === "Enter") {
          e.preventDefault();
          const row = rows[focusIdx];
          if (row?.id) onOpenRun(row.id);
        } else if (e.key === "Escape") {
          // sec 18: Escape in the fleet returns focus to the composer.
          e.preventDefault();
          (e.currentTarget as HTMLDivElement).blur();
          requestComposerFocus();
        }
      }}
    >
      {clampedOffset > 0 && (
        <button
          className="fleet-bar__nav"
          type="button"
          aria-label="Previous fleet rows"
          onClick={() => {
            setOffset((value) => Math.max(0, value - 1));
            moveFocus(Math.max(0, focusIdx - 1));
          }}
        >
          <Icon name="chevDown" size={14} />
        </button>
      )}
      <div className="fleet-bar__window">
        {visible.map((row, visibleIndex) => (
          <FleetRow
            key={row.id}
            row={row}
            absoluteIndex={clampedOffset + visibleIndex}
            focusIdx={focusIdx}
            setFocusIdx={setFocusIdx}
            onOpenRun={onOpenRun}
          />
        ))}
      </div>
      {clampedOffset < maxOffset && (
        <button
          className="fleet-bar__nav fleet-bar__nav--down"
          type="button"
          aria-label="Next fleet rows"
          onClick={() => {
            setOffset((value) => Math.min(maxOffset, value + 1));
            moveFocus(Math.min(rows.length - 1, focusIdx + 1));
          }}
        >
          <Icon name="chevDown" size={14} />
        </button>
      )}
    </div>
  );
}

export { type FleetBarProps };
