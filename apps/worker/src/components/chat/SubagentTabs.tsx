import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import type { AuditNode, SubagentEntry } from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import { FamiliarBadge } from "../familiar/FamiliarBadge";
import { formatCostMicros } from "./RunSectionFormat";
import "./SubagentTabs.css";

// The split-pane subagent surface that opens beside the chat transcript: one
// tab per opened subagent, and for the active tab a small thread drawn ONLY
// from data the stream and audit endpoints actually carry.
//
// Deliberate omissions versus the design mock (recorded in the cluster report):
// - no per-step list — the ChatSubagent frame carries `step_count` only, so we
//   show the count and keep the stream honest about what it contains;
// - no "what it returned" paragraph — `subagent_end` carries status only;
// - no per-subagent composer — ChatRequest addresses a conversation, not a
//   child run, and no steer-to-subagent API exists.

export interface SubagentTabsProps {
  /** Every subagent the current turn spawned (turn.subagents). */
  subagents: SubagentEntry[];
  /** Keys (SubagentEntry.key) of the open tabs, in the order they opened. */
  openKeys: string[];
  /** The selected tab. When absent or stale, the last open tab is shown. */
  activeKey: string | null;
  /** turn.runId — the parent run whose audit tree carries per-child spend. */
  parentRunId?: string;
  /** turn.ended — lets an unsettled status read honestly (see stateWord). */
  turnEnded: boolean;
  onSelect(key: string): void;
  onClose(key: string): void;
  onCloseAll(): void;
}

// Per-child spend is real data (client.auditTree -> AuditNode.cost fields) but
// arrives out of band, so it gets its own honest lifecycle instead of a
// placeholder figure.
type SpendState =
  | { phase: "idle" }
  | { phase: "loading" }
  | { phase: "ready"; byRunId: Record<string, AuditNode> }
  | { phase: "unavailable" };

export function SubagentTabs({
  subagents,
  openKeys,
  activeKey,
  parentRunId,
  turnEnded,
  onSelect,
  onClose,
  onCloseAll,
}: SubagentTabsProps) {
  const [spend, setSpend] = useState<SpendState>({ phase: "idle" });
  const spendSequence = useRef(0);
  const openCount = openKeys.length;

  useEffect(() => {
    if (!parentRunId || openCount === 0) {
      spendSequence.current += 1;
      setSpend({ phase: "idle" });
      return;
    }
    // Re-fetch on tab switch and when the turn settles so the figure tracks the
    // live run; the sequence guard drops answers that arrive out of order.
    const sequence = ++spendSequence.current;
    setSpend({ phase: "loading" });
    void client.auditTree(parentRunId)
      .then((result) => {
        if (spendSequence.current !== sequence) return;
        const byRunId: Record<string, AuditNode> = {};
        const walk = (node: AuditNode) => {
          byRunId[node.run_id] = node;
          node.children?.forEach(walk);
        };
        walk(result.root);
        setSpend({ phase: "ready", byRunId });
      })
      .catch(() => {
        if (spendSequence.current === sequence) setSpend({ phase: "unavailable" });
      });
  }, [parentRunId, openCount, activeKey, turnEnded]);

  // Tab identity is the timeline entry key; the host supplies a runId-tagged
  // snapshot, so keys resolve against exactly the turn that minted them.
  const open = openKeys
    .map((key) => subagents.find((entry) => entry.key === key))
    .filter((entry): entry is SubagentEntry => Boolean(entry));
  // Closing a tab removes the focused element; put focus on the active tab
  // rather than letting it drop to <body>. (The host restores focus itself
  // when the last tab closes and this component unmounts.)
  const openCountNow = open.length;
  const activeKeyNow = open.find((entry) => entry.key === activeKey)?.key
    ?? open[open.length - 1]?.key;
  useEffect(() => {
    if (openCountNow > 0 && document.activeElement === document.body && activeKeyNow) {
      document.getElementById(`subtab-${activeKeyNow}`)?.focus();
    }
  }, [openCountNow, activeKeyNow]);
  if (open.length === 0) return null;
  const active = open.find((entry) => entry.key === activeKey) ?? open[open.length - 1];

  // The WAI-ARIA tabs pattern: arrows move selection within the strip.
  function onStripKeyDown(event: ReactKeyboardEvent) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    const index = open.findIndex((entry) => entry.key === active.key);
    const next = event.key === "ArrowRight"
      ? open[(index + 1) % open.length]
      : open[(index - 1 + open.length) % open.length];
    event.preventDefault();
    onSelect(next.key);
    document.getElementById(`subtab-${next.key}`)?.focus();
  }

  return (
    <section className="subtabs" aria-label="Subagents">
      <div className="subtabs-strip" role="tablist" aria-label="Open subagents" onKeyDown={onStripKeyDown}>
        {open.map((entry) => {
          const selected = entry.key === active.key;
          return (
            <div className="subtabs-tab" data-active={selected || undefined} key={entry.key}>
              <button
                aria-controls="subtabs-thread"
                aria-selected={selected}
                className="subtabs-tab-select"
                id={`subtab-${entry.key}`}
                onClick={() => onSelect(entry.key)}
                role="tab"
                type="button"
              >
                <FamiliarBadge
                  state={badgeState(entry, turnEnded)}
                  genotype={entry.familiarGenotype}
                  label={entry.name}
                />
                <span>{entry.name ?? "Subagent"}</span>
              </button>
              <button
                aria-label={`Close ${entry.name ?? "subagent"} tab`}
                className="subtabs-tab-close"
                onClick={() => onClose(entry.key)}
                type="button"
              >×</button>
            </div>
          );
        })}
        <button
          aria-label="Close all subagent tabs"
          className="subtabs-close-all"
          onClick={onCloseAll}
          title="Close all"
          type="button"
        >—</button>
      </div>
      <div
        aria-labelledby={`subtab-${active.key}`}
        className="subtabs-thread"
        id="subtabs-thread"
        role="tabpanel"
      >
        <SubagentThread
          entry={active}
          spend={spend}
          turnEnded={turnEnded}
        />
      </div>
    </section>
  );
}

function SubagentThread({
  entry,
  spend,
  turnEnded,
}: {
  entry: SubagentEntry;
  spend: SpendState;
  turnEnded: boolean;
}) {
  const state = stateWord(entry, turnEnded);
  // Skills the spawn actually granted, from the stream frame plus the spawn
  // rule receipt. This is the allowed-to-do surface the SDK provides; the full
  // effective-grants list rides only direct SpawnResults, never chat frames.
  const skills = [...new Set([...entry.skills, ...(entry.spawnRule?.skills_added ?? [])])];
  return (
    <div className="subtabs-thread-inner">
      <div className="subtabs-instruction-row">
        {/* aria-label is prohibited naming on a <p>; a visually hidden lead-in
            gives assistive tech the same reading. */}
        <p className="subtabs-instruction">
          <span className="visually-hidden">
            Instruction given to {entry.name ?? "this subagent"}:{" "}
          </span>
          {entry.task}
        </p>
      </div>
      <div className="subtabs-identity">
        <FamiliarBadge
          state={badgeState(entry, turnEnded)}
          genotype={entry.familiarGenotype}
          label={entry.name}
        />
        <strong>{entry.name ?? "Subagent"}</strong>
        <span className="subtabs-state" data-state={state.key}>{state.word}</span>
        {entry.role && <span className="subtabs-role">{entry.role}</span>}
        {entry.spawnRule && (
          <span className="subtabs-capability" title={`Spawn policy ${entry.spawnRule.id}`}>
            {entry.spawnRule.capability}
          </span>
        )}
      </div>
      {/* The stream carries the step COUNT only — never a step list. */}
      {entry.stepCount != null && (
        <p className="subtabs-steps">
          {entry.stepCount} {entry.stepCount === 1 ? "step" : "steps"} recorded.
          <span> The chat stream carries the count only; each step lives in the full event log.</span>
        </p>
      )}
      <div className="subtabs-allowed">
        <span className="subtabs-allowed-title">What it was allowed to do</span>
        <div className="subtabs-allowed-card">
          <span className="subtabs-allowed-skills">
            {skills.length > 0
              ? skills.join(", ")
              : "Its baseline skills only — the stream reported no extra grants."}
          </span>
          <span className="subtabs-allowed-spend">{spendText(spend, entry.childRunId)}</span>
        </div>
        <span className="subtabs-allowed-caption">
          Narrower than the agent above it, which is narrower than you. That only
          ever tightens on the way down.
        </span>
      </div>
    </div>
  );
}

// Status words stay inside what `subagent_end` proved. `undefined` while the
// turn is live honestly means still running; after the turn has ended it means
// an un-upgraded kernel never emitted the settle frame, and saying "finished"
// would be an invention.
function stateWord(
  entry: SubagentEntry,
  turnEnded: boolean,
): { key: string; word: string } {
  switch (entry.status) {
    case "ok":
      return { key: "ok", word: "finished" };
    case "degraded":
      return { key: "degraded", word: "finished, degraded" };
    case "error":
      return { key: "error", word: "failed" };
    default:
      return turnEnded
        ? { key: "unreported", word: "no completion reported" }
        : { key: "running", word: "still working" };
  }
}

function badgeState(entry: SubagentEntry, turnEnded: boolean): "ready" | "working" {
  const settled = entry.status !== undefined && entry.status !== "running";
  return !turnEnded && !settled ? "working" : "ready";
}

function spendText(spend: SpendState, childRunId: string): string {
  if (spend.phase === "loading") return "spend loading…";
  if (spend.phase === "unavailable") return "spend unavailable";
  if (spend.phase === "idle") return "spend not recorded";
  const node = childRunId ? spend.byRunId[childRunId] : undefined;
  if (!node) return "no spend recorded yet";
  // A node without cost/action fields is an absent measurement, not zero —
  // "0 actions · $0.00" would present the gap as a reading.
  const hasCost = node.total_cost_micros != null || node.cost_micros != null;
  const hasActions = node.actions != null;
  if (!hasCost && !hasActions) return "spend not recorded for this run";
  const parts: string[] = [];
  if (hasActions) parts.push(`${node.actions} ${node.actions === 1 ? "action" : "actions"}`);
  parts.push(hasCost
    ? formatCostMicros(Number(node.total_cost_micros ?? node.cost_micros))
    : "cost not recorded");
  return parts.join(" · ");
}
