import { useCallback, useMemo, useState } from "react";
import type { RunEffectView, RunRevertResult } from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";

type UndoApi = Pick<typeof client, "runEffects" | "revertRun">;

// The literal client callsites (tests inject a stub through the `api` prop;
// the worker-surface ledger requires the real methods to be reachable here).
const liveApi: UndoApi = {
  runEffects: (runId) => client.runEffects(runId),
  revertRun: (runId, approvals) => client.revertRun(runId, approvals),
};

// The user-facing reading of each revert outcome. "approval_pending" is a
// waiting state, not a failure: the kernel held the compensation for a human,
// exactly as it would have held the original action.
const OUTCOME_LABELS: Record<RunRevertResult["outcome"], string> = {
  reverted: "Undone",
  revert_failed: "Failed - the change may still stand",
  not_undoable: "Can't be undone",
  already_settled: "Already handled",
  approval_pending: "Waiting for your approval",
};

const STATUS_LABELS: Record<RunEffectView["status"], string> = {
  recorded: "Can be undone",
  not_undoable: "Can't be undone",
  reverted: "Undone",
  revert_failed: "Undo failed earlier",
};

export function RunUndoPanel({ runId, api = liveApi }: { runId: string; api?: UndoApi }) {
  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<"idle" | "loading" | "listed" | "reverting" | "done" | "error">("idle");
  const [effects, setEffects] = useState<RunEffectView[]>([]);
  const [results, setResults] = useState<RunRevertResult[]>([]);

  const load = useCallback(async () => {
    setOpen(true);
    setPhase("loading");
    try {
      const body = await api.runEffects(runId);
      setEffects(body.effects);
      setPhase("listed");
    } catch {
      setPhase("error");
    }
  }, [api, runId]);

  const pendingApprovals = useMemo(() => {
    const approvals: Record<string, string> = {};
    for (const row of results) {
      if (row.outcome === "approval_pending" && row.approval_id) {
        approvals[String(row.seq)] = row.approval_id;
      }
    }
    return approvals;
  }, [results]);

  const revert = useCallback(async (approvals?: Record<string, string>) => {
    setPhase("reverting");
    try {
      const body = await api.revertRun(runId, approvals);
      setResults(body.results);
      setPhase("done");
    } catch {
      setPhase("error");
    }
  }, [api, runId]);

  if (!open) {
    return (
      <button type="button" className="run-undo-toggle" onClick={load}>
        Undo actions…
      </button>
    );
  }
  if (phase === "loading") return <p className="run-undo-note" role="status">Checking what this turn changed…</p>;
  if (phase === "error") {
    return (
      <p className="run-undo-note" role="alert">
        Couldn't load this turn's actions. <button type="button" onClick={load}>Try again</button>
      </p>
    );
  }

  const rows: Array<RunEffectView | RunRevertResult> =
    phase === "done" || phase === "reverting" ? (results.length ? results : effects) : effects;

  return (
    <UndoLedger
      effects={effects}
      rows={rows}
      showConfirm={phase === "listed"}
      pendingApprovals={phase === "done" ? pendingApprovals : {}}
      onRevert={revert}
    />
  );
}

function UndoLedger({ effects, rows, showConfirm, pendingApprovals, onRevert }: {
  effects: RunEffectView[];
  rows: Array<RunEffectView | RunRevertResult>;
  showConfirm: boolean;
  pendingApprovals: Record<string, string>;
  onRevert(approvals?: Record<string, string>): void;
}) {
  const undoable = effects.filter((row) => row.undoable).length;
  const hasPending = Object.keys(pendingApprovals).length > 0;
  return (
    <section className="run-undo-panel" aria-label="Undo actions for this turn">
      {effects.length === 0 ? (
        <p className="run-undo-note">This turn made no reversible changes.</p>
      ) : (
        <ul className="run-undo-list">
          {[...rows].sort((a, b) => b.seq - a.seq).map((row) => (
            <li key={row.seq} data-undoable={"outcome" in row ? undefined : row.undoable}>
              <span className="run-undo-summary">{row.summary || row.verb}</span>
              <span className="run-undo-state">
                {"outcome" in row ? OUTCOME_LABELS[row.outcome] : STATUS_LABELS[row.status]}
              </span>
            </li>
          ))}
        </ul>
      )}
      {showConfirm && undoable > 0 && (
        <button type="button" className="run-undo-confirm" onClick={() => onRevert()}>
          Undo {undoable === 1 ? "this action" : `these ${undoable} actions`}
        </button>
      )}
      {hasPending && (
        <p className="run-undo-note">
          Some steps need your approval first. Approve them, then finish here.{" "}
          <button type="button" className="run-undo-confirm" onClick={() => onRevert(pendingApprovals)}>
            Finish undo
          </button>
        </p>
      )}
      <p className="run-undo-governance">Undo runs through the same policy and approvals as the original actions.</p>
    </section>
  );
}
