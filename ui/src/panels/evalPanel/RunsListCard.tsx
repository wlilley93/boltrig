import { RunLink } from "@/panels/shared";
import { EmptyState, Field, Select } from "@/panels/ux";
import type { EvalState } from "./useEvalState";

export function RunsListCard({ s }: { s: EvalState }) {
  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>3. Runs</h3>
        <div className="panel__actions">
          <Field label="Filter by case">
            <Select
              value={s.filterCase}
              ariaLabel="Filter by case"
              onChange={s.setFilterCase}
              options={[{ value: "", label: "All cases" }, ...s.caseIdOptions.slice(1)]}
            />
          </Field>
          <button className="btn" onClick={() => s.runs.reload()}>
            Refresh
          </button>
        </div>
      </div>
      <div className="list-card__body">
        {s.runs.loading && !s.runs.data && <p className="muted">Loading...</p>}
        {s.runs.error && <p className="error">Could not load: {s.runs.error}</p>}
        {!s.runs.loading && s.runList.length === 0 && (
          <EmptyState
            title="No eval runs yet"
            body="Create and run a case to see results here."
          />
        )}
        {s.runList.map((r) => (
          <div className="row-line" key={r.id}>
            <div>
              <code>{r.case_id}</code>
              <div className="muted">
                {r.run_id ? <RunLink runId={r.run_id} /> : "-"}
              </div>
            </div>
            <div className="kv">
              <span className={`badge ${r.passed ? "badge--pass" : "badge--fail"}`}>
                {r.passed ? "pass" : "fail"}
              </span>
              <span className="badge" title="0 to 1">score {r.score}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
