import { useEffect, useState } from "react";
import type { NormalizedTurn } from "@wlilley93/boltrig-web-sdk";

interface WorkDisclosureProps {
  turn: NormalizedTurn;
  /** True when this turn comes from the durable transcript rather than the
      live stream. */
  settled?: boolean;
  /** Epoch ms when this client first saw the live turn; null when the turn
      was never watched here. */
  startedAt?: number | null;
  /** Seconds measured while this client watched the turn run. ChatEvent
      frames carry no timestamps, so a turn that settled elsewhere has no
      duration to state - the label then says "Worked" with no number. */
  durationSeconds?: number | null;
}

function formatSeconds(total: number): string {
  if (total < 60) return `${total}s`;
  return `${Math.floor(total / 60)}m ${total % 60}s`;
}

/** The collapsed one-line work disclosure over a hairline: tool activity is
 * tucked behind "Worked for Ns" (or "Working" while live). Durations are only
 * ever stated from local observation of the run - never invented for turns
 * this client did not watch. */
export function WorkDisclosure({
  turn,
  settled = false,
  startedAt = null,
  durationSeconds = null,
}: WorkDisclosureProps) {
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const live = !settled && !turn.ended;

  useEffect(() => {
    if (!live || startedAt == null) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [live, startedAt]);

  if (turn.tools.length === 0) return null;

  const seconds = durationSeconds
    ?? (startedAt != null ? Math.max(0, Math.round((now - startedAt) / 1_000)) : null);
  const label = live
    ? seconds != null ? `Working · ${formatSeconds(seconds)}` : "Working"
    : seconds != null ? `Worked for ${formatSeconds(seconds)}` : "Worked";
  const count = turn.tools.length;

  return (
    <div className="work-disclosure">
      <button
        aria-expanded={open}
        className="work-toggle"
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        <span>{label} · {count} {count === 1 ? "tool call" : "tool calls"}</span>
        <svg aria-hidden fill="none" height="13" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.2" viewBox="0 0 24 24" width="13">
          <polyline points="9 6 15 12 9 18" />
        </svg>
      </button>
      {open && (
        <div className="activity">
          {turn.tools.map((tool, index) => (
            <div className="activity-row" key={tool.callId ?? `${tool.key}-${index}`}>
              <span className={`activity-dot ${tool.status}`} />
              <span>{tool.verb}</span>
              <small>{tool.status}</small>
            </div>
          ))}
        </div>
      )}
      <div className="work-rule" />
    </div>
  );
}
