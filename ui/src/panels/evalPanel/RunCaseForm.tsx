import { CodeBlock, GrantList, RunLink } from "@/panels/shared";
import { Field, Hint, Select } from "@/panels/ux";
import type { EvalState } from "./useEvalState";

export function RunCaseForm({ s }: { s: EvalState }) {
  return (
    <div className="form">
      <div className="form__title">2. Run a case</div>
      <div className="form__actions">
        <Field label="Case" hint="Pick the case to run.">
          <Select value={s.runId} ariaLabel="Case to run" onChange={s.setRunId} options={s.caseIdOptions} />
        </Field>
        <button className="btn btn--primary" disabled={s.runBusy} onClick={s.run}>
          {s.runBusy ? "Running..." : "Run case"}
        </button>
        {s.runError && <span className="error">{s.runError}</span>}
      </div>
      {s.runResult ? (
        <div className="stack">
          <div className="kv">
            <span className={`badge ${s.runResult.passed ? "badge--pass" : "badge--fail"}`}>
              {s.runResult.passed ? "passed" : "failed"}
            </span>
            {typeof s.runResult.score === "number" && (
              <span className="badge" title="0 to 1">score {s.runResult.score}</span>
            )}
            {s.runResult.run_id && <RunLink runId={s.runResult.run_id} />}
          </div>
          <div className="row-line">
            <span className="muted">Permissions the run actually used</span>
            <GrantList grants={s.runResult.detail?.effective_grants} />
          </div>
          <CodeBlock value={s.runResult.detail ?? {}} />
        </div>
      ) : (
        <Hint>Run a case to see pass/fail and the permissions it used.</Hint>
      )}
    </div>
  );
}
