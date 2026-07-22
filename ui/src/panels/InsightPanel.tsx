// Round Three insight surface (Epic OBS). Cost rollup, audit search and a runs
// list - all scope-filtered server-side (SEC-33): a department-scoped caller
// only ever sees their own departments' runs. The copy makes that explicit so a
// viewer understands an empty result is scoping, not a bug. Audit export is
// gated to author/admin roles (a 403 renders as a denial).
//
// Thin orchestrator: the state + data hooks live in insightPanel/ (useInsightState
// composes useInsightFields + useInsightActions) and each card renders through
// its own sub-component, so every file stays under the structural floor.

import { useState } from "react";

import { AuditSearchForm } from "./insightPanel/AuditSearchForm";
import { Budgets } from "./insightPanel/Budgets";
import { CostCard } from "./insightPanel/CostCard";
import { RunsCard } from "./insightPanel/RunsCard";
import { useInsightState } from "./insightPanel/useInsightState";
import { PageIntro } from "./ux";
import { SegmentedV2 } from "./uxForm";

type InsightMode = "overview" | "audit" | "budgets";

export function InsightPanel() {
  const s = useInsightState();
  const [mode, setMode] = useState<InsightMode>("overview");

  return (
    <section className="panel">
      <PageIntro
        title="Insight"
        lead="See what your departments have been doing, what it cost, and search the full audit trail."
        how="Every number here is scoped to what you're allowed to see (SEC-33), so an empty result can simply mean nothing in your scope - not a bug."
        actions={
          mode === "overview" ? (
            <button className="btn btn--primary" onClick={s.refresh}>
              Refresh overview
            </button>
          ) : undefined
        }
      />

      <div className="surface-mode">
        <SegmentedV2
          value={mode}
          onChange={(value) => setMode(value as InsightMode)}
          ariaLabel="Insight task"
          options={[
            { value: "overview", label: "Overview" },
            { value: "audit", label: "Audit" },
            { value: "budgets", label: "Budgets" },
          ]}
        />
      </div>

      {mode === "overview" && (
        <div className="cols">
          <CostCard s={s} />
          <RunsCard s={s} />
        </div>
      )}
      {mode === "audit" && <AuditSearchForm s={s} />}
      {mode === "budgets" && <Budgets />}
    </section>
  );
}
