import { EmptyState, FetchError } from "@/panels/ux";
import type { EvalState } from "./useEvalState";

export function SavedCasesCard({ s }: { s: EvalState }) {
  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>Saved cases</h3>
        <button className="btn" onClick={() => s.cases.reload()}>
          Refresh
        </button>
      </div>
      <div className="list-card__body">
        {s.cases.loading && !s.cases.data && <p className="muted">Loading...</p>}
        <FetchError
          error={s.cases.error}
          status={s.cases.errorStatus}
          onRetry={s.cases.reload}
        />
        {!s.cases.loading && !s.cases.error && s.savedCases.length === 0 && (
          <EmptyState
            title="No saved cases"
            body="Create a case to make it available for repeatable runs."
          />
        )}
        {s.savedCases.map((evalCase) => (
          <div className="row-line" key={evalCase.id}>
            <div>
              <strong>{evalCase.id}</strong>
              <div className="muted">
                {evalCase.target_kind} · {evalCase.target_ref}
              </div>
              {evalCase.labels.length > 0 && (
                <div className="kv">
                  {evalCase.labels.map((label) => (
                    <span className="tag" key={label}>
                      {label}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <button
              className="btn"
              aria-label={`Use case ${evalCase.id}`}
              onClick={() => s.setRunId(evalCase.id)}
            >
              Use
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
