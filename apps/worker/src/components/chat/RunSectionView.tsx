import { useEffect, useRef, useState } from "react";
import {
  BoltrigApiError,
  type AuditNode,
  type FamiliarGenotype,
  type RunTopologyNode,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import { FamiliarBadge } from "../familiar/FamiliarBadge";
import { formatCostMicros, statusPhrase, statusTone } from "./RunSectionFormat";
import "./RunSectionView.css";

// The "drilling section" drawing of a run: one column per delegated step from
// client.runTopology(runId), helper sub-bores for the step's own children, a
// fixed legend column, and a plain-vs-technical subtitle.
//
// Honesty decisions versus the design mock (recorded in the cluster report):
// - ONE visual register: the coloured top edge encodes status, which the
//   topology really carries. The design's second register — a dashed rail with
//   "not held in place" for non-durable steps — is not drawn at all, because
//   RunTopologyNode has no durable field and inferring one from id equality is
//   an undocumented coupling.
// - Columns follow the order the kernel serves (its ledger order). The server
//   sorts children by item id and exposes no timestamps, so the drawing never
//   claims "time runs left to right".
// - No role hues: the topology carries a member name, not a role taxonomy, so
//   bores keep one neutral tint and identity comes from the FamiliarBadge with
//   a real genotype when the caller can supply one.
// - Per-step captions come only from real fields: status (plain phrase), task,
//   member, attempts, degraded, cycle, and audit actions/cost.

export interface RunSectionViewProps {
  /** The run to draw. The caller resolves it (e.g. turn.runId). */
  runId: string;
  /** Plain-language title; falls back to the topology root's task text. */
  title?: string;
  /** Technical register: run id and depth in the subtitle instead of prose. */
  devDetails?: boolean;
  /**
   * Real Familiar genotypes keyed by child run id, built from turn.subagents.
   * Steps without one render the neutral unbound orb — never a minted identity.
   */
  familiarsByRunId?: Record<string, FamiliarGenotype | null | undefined>;
  onBack(): void;
}

type SectionState = "loading" | "ready" | "denied" | "not-found" | "unavailable";

export interface SectionColumn {
  node: RunTopologyNode;
  index: number;
  helpers: RunTopologyNode[];
  /** Descendants below the drawn helper level (drawn as a count, not a lie). */
  deeper: number;
}

export function RunSectionView({
  runId,
  title,
  devDetails,
  familiarsByRunId,
  onBack,
}: RunSectionViewProps) {
  const [state, setState] = useState<SectionState>("loading");
  const [root, setRoot] = useState<RunTopologyNode | null>(null);
  const [auditByRunId, setAuditByRunId] = useState<Record<string, AuditNode>>({});
  const sequence = useRef(0);
  const backRef = useRef<HTMLButtonElement>(null);

  // The drawing covers the conversation surface; move focus in with it so
  // keyboard and screen-reader users land on the one control that exits.
  useEffect(() => {
    backRef.current?.focus();
  }, []);

  useEffect(() => {
    const current = ++sequence.current;
    setState("loading");
    setRoot(null);
    setAuditByRunId({});
    // Topology is load-bearing; the audit tree only annotates, so its failure
    // must not take the drawing down (RunsView inspect() precedent).
    void Promise.allSettled([
      client.runTopology(runId),
      client.auditTree(runId),
    ]).then(([topology, audit]) => {
      if (sequence.current !== current) return;
      if (topology.status === "fulfilled") {
        setRoot(topology.value.root);
        setState("ready");
      } else {
        setState(failureState(topology.reason));
      }
      if (audit.status === "fulfilled") {
        const byRunId: Record<string, AuditNode> = {};
        const walk = (node: AuditNode) => {
          byRunId[node.run_id] = node;
          node.children?.forEach(walk);
        };
        walk(audit.value.root);
        setAuditByRunId(byRunId);
      }
    });
  }, [runId]);

  const columns: SectionColumn[] = (root?.children ?? []).map((node, index) => ({
    node,
    index,
    helpers: node.children,
    deeper: node.children.reduce((sum, child) => sum + countDescendants(child), 0),
  }));
  const delegatingCount = columns.filter((column) => column.helpers.length > 0).length;
  const anyHelpers = delegatingCount > 0;

  return (
    <section aria-label="Run section" className="runsection">
      <div className="runsection-inner">
        <header className="runsection-head">
          <div>
            <h1>{title ?? root?.task ?? "This run"}</h1>
            <p className="runsection-sub">
              {subtitleText(state, runId, root, columns.length, delegatingCount, devDetails)}
            </p>
          </div>
          <button className="runsection-back" onClick={onBack} ref={backRef} type="button">
            Back to the conversation
          </button>
        </header>

        {state === "loading" && (
          <p className="runsection-status" role="status">Loading what ran…</p>
        )}
        {state === "denied" && (
          <p className="runsection-status">Your current role cannot view this run's execution tree.</p>
        )}
        {state === "not-found" && (
          <p className="runsection-status">No topology is recorded for this run.</p>
        )}
        {state === "unavailable" && (
          <p className="runsection-status">The run's topology could not be reached. It is safe to retry.</p>
        )}

        {state === "ready" && root && columns.length === 0 && (
          <div className="runsection-card runsection-empty">
            <p>
              This run did every step itself — nothing was delegated, so there is
              no section to draw.
              {root.member ? ` ${root.member} worked` : " The head agent worked"} under
              your authority for the whole run
              {root.status === "awaiting_human"
                ? ", and it is waiting for you now."
                : ` (${statusPhrase(root.status)}).`}
            </p>
          </div>
        )}

        {state === "ready" && root && columns.length > 0 && (
          <div className="runsection-card">
            <div className="runsection-scroll">
              <div className="runsection-legend">
                <div className="runsection-legend-zone runsection-legend-head">
                  <span>Every step</span>
                  <small>checked the same way, whatever it is</small>
                </div>
                <div className="runsection-legend-zone runsection-legend-bore">
                  <span>{root.member ?? "the head agent"}</span>
                  <small>acts under your authority, and never beyond it</small>
                </div>
                {anyHelpers && (
                  <div className="runsection-legend-zone runsection-legend-workers">
                    <span>its helpers</span>
                    <small>one job each, narrower still</small>
                  </div>
                )}
              </div>
              <div
                className="runsection-grid"
                style={{ gridTemplateColumns: `repeat(${columns.length}, minmax(132px, 1fr))` }}
              >
                {columns.map((column) => (
                  <SectionColumnView
                    audit={auditByRunId[column.node.run_id]}
                    column={column}
                    familiarsByRunId={familiarsByRunId}
                    key={column.node.run_id}
                  />
                ))}
              </div>
            </div>
          </div>
        )}

        {state === "ready" && root && (
          <div className="runsection-howto">
            <span>How to read it</span>
            <p>
              Steps are drawn in the order the kernel recorded them — the run's
              ledger order, not the clock. Every step is checked the same way,
              whatever it does. Work drops downward from the step that asked for
              it, and narrows as it goes: what an agent may do is a subset of
              what the thing above it may do, never more. Amber is where it
              stopped and waited for you.
            </p>
          </div>
        )}
      </div>
    </section>
  );
}

function SectionColumnView({
  column,
  audit,
  familiarsByRunId,
}: {
  column: SectionColumn;
  audit?: AuditNode;
  familiarsByRunId?: Record<string, FamiliarGenotype | null | undefined>;
}) {
  const { node, index, helpers, deeper } = column;
  const tone = statusTone(node.status);
  const gated = node.status === "awaiting_human";
  const auditCost = audit
    ? Number(audit.total_cost_micros ?? audit.cost_micros ?? 0)
    : null;
  return (
    <div className="runsection-col" data-status={node.status}>
      <div className="runsection-col-head">
        <span className="runsection-col-n">{index + 1}</span>
        <span className="runsection-col-name" title={node.task}>{node.task}</span>
      </div>
      <div className="runsection-bore" data-tone={tone}>
        <FamiliarBadge
          state={node.status === "in_flight" ? "working" : "ready"}
          genotype={familiarsByRunId?.[node.run_id]}
          label={node.member ?? undefined}
        />
        <span className="runsection-caption">{statusPhrase(node.status)}</span>
        {gated && <span className="runsection-gate-chip">held</span>}
        {gated && <span className="runsection-gate" />}
      </div>
      {helpers.length > 0 && (
        <>
          <div className="runsection-workers">
            {helpers.slice(0, 6).map((helper) => (
              <div
                className="runsection-worker"
                data-tone={statusTone(helper.status)}
                key={helper.run_id}
                title={`${helper.task} · ${statusPhrase(helper.status)}`}
              />
            ))}
          </div>
          <div className="runsection-worker-caption">
            {helpers.length} {helpers.length === 1 ? "helper" : "helpers"}
            {deeper > 0 ? ` · ${deeper} deeper not drawn` : ""}
          </div>
        </>
      )}
      <div className="runsection-col-meta">
        {node.member && <span>{node.member}</span>}
        {node.attempts > 1 && <span>{node.attempts} attempts</span>}
        {node.degraded && <span className="runsection-degraded">degraded result</span>}
        {node.cycle && <span>cycle detected</span>}
        {audit && (
          <span>{audit.actions ?? 0} actions · {formatCostMicros(auditCost ?? 0)}</span>
        )}
      </div>
    </div>
  );
}

// Both registers of the subtitle are derived from the same real topology; the
// plain one drops ids, not facts.
function subtitleText(
  state: SectionState,
  runId: string,
  root: RunTopologyNode | null,
  steps: number,
  delegating: number,
  devDetails?: boolean,
): string {
  if (state !== "ready" || !root) return devDetails ? runId : "What this run set in motion";
  const maxDepth = deepestDepth(root) - root.depth;
  if (devDetails) return `${runId} · ${steps} ${steps === 1 ? "step" : "steps"} · depth ${maxDepth}`;
  if (steps === 0) return "No steps were delegated";
  const stepsPart = `${steps} delegated ${steps === 1 ? "step" : "steps"}`;
  return delegating > 0
    ? `${stepsPart}, ${delegating} of them delegated further`
    : stepsPart;
}

function countDescendants(node: RunTopologyNode): number {
  return node.children.reduce((sum, child) => sum + 1 + countDescendants(child), 0);
}

function deepestDepth(node: RunTopologyNode): number {
  return node.children.reduce(
    (deepest, child) => Math.max(deepest, deepestDepth(child)),
    node.depth,
  );
}

// Mirrors ParityViews' failureState so the two run surfaces degrade alike.
function failureState(error: unknown): Exclude<SectionState, "loading" | "ready"> {
  if (error instanceof BoltrigApiError) {
    if (error.status === 401 || error.status === 403) return "denied";
    if (error.status === 404) return "not-found";
  }
  return "unavailable";
}
