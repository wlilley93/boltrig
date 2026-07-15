// Round Three evaluation harness (Epic EVAL). Create a case, run it (the runner
// spawns the target through the kernel chokepoint under the INITIATOR's grants,
// so an eval can never call a verb the initiator lacks - SEC-29), and list runs.
// A run shows passed + the child's effective_grants, which is the no-escalation
// evidence: e.g. an assertion {"forbidden_grants":["ticket.create"]} passes only
// if that grant is absent from effective_grants.
//
// Thin orchestrator: the state + data hooks live in evalPanel/ (useEvalState
// composes useEvalFields + useEvalActions) and each section renders through its
// own sub-component, so every file stays under the structural floor.

import { CreateCaseForm } from "./evalPanel/CreateCaseForm";
import { RunCaseForm } from "./evalPanel/RunCaseForm";
import { RunsListCard } from "./evalPanel/RunsListCard";
import { SavedCasesCard } from "./evalPanel/SavedCasesCard";
import { useEvalState } from "./evalPanel/useEvalState";
import { InfoCallout, PageIntro } from "./ux";

export function EvalPanel() {
  const s = useEvalState();

  return (
    <section className="panel">
      <PageIntro
        title="Eval"
        lead="Test that a skill or workflow does the right thing - and only uses the permissions it's supposed to."
        how="1. Create a case (what to run + what to assert). 2. Run it. 3. Review pass/fail with the permissions the run actually had. The test runs under your permissions, so it can never exceed them."
      />

      <div className="cols">
        <div className="stack">
          <CreateCaseForm s={s} />
          <RunCaseForm s={s} />
        </div>
        <div className="stack">
          <SavedCasesCard s={s} />
          <RunsListCard s={s} />
        </div>
      </div>

      <InfoCallout>
        "No-escalation" means the run can never gain more permissions than you
        have. The permissions a run actually used are its{" "}
        <code>effective_grants</code> - the proof it stayed within bounds.
      </InfoCallout>
    </section>
  );
}
