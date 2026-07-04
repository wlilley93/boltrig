import { CodeBlock, RunLink } from "@/panels/shared";
import {
  AUDIT_STATUS,
  Field,
  Hint,
  Select,
  StatusBadge,
} from "@/panels/ux";
import type { InsightState } from "./useInsightState";
import { whenText } from "./formatting";

export function AuditSearchForm({ s }: { s: InsightState }) {
  return (
    <div className="form">
      <div className="form__title">Audit search</div>
      <Hint>
        Search the tamper-evident log of every governed action. Results are
        limited to your scope.
      </Hint>
      <div className="form__grid">
        <Field label="Actor" hint="Who performed the action.">
          <Select value={s.actor} ariaLabel="Actor" onChange={s.setActor} options={s.actorOptions} />
        </Field>
        <Field label="Action" hint="The verb that was called.">
          <Select value={s.verb} ariaLabel="Action" onChange={s.setVerb} options={s.verbOptions} />
        </Field>
        <Field label="Run id" hint="Paste a run id to see only its events." example="run_5f3a...">
          <input value={s.run} onChange={(e) => s.setRun(e.target.value)} />
        </Field>
      </div>
      <div className="form__actions">
        <button className="btn btn--primary" disabled={s.searchBusy} onClick={s.search}>
          {s.searchBusy ? "Searching..." : "Search"}
        </button>
        <button className="btn" disabled={s.exportBusy} onClick={s.exportAudit} title="Download the full audit log as a file - available to authors and admins.">
          {s.exportBusy ? "Exporting..." : "Export audit"}
        </button>
      </div>
      {s.searchError && <p className="error">{s.searchError}</p>}
      {s.exportError && <p className="notice warn">Export: {s.exportError}</p>}

      {s.rows && (
        <>
          <p className="muted">
            {s.rows.length === 0
              ? "No audit events match - try clearing a filter (results are limited to your scope)."
              : `${s.rows.length} result(s); scope: ${s.searchScope || "all"}`}
          </p>
          {s.rows.length > 0 && (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>When</th>
                    <th>Actor</th>
                    <th>Action</th>
                    <th>Status</th>
                    <th>Run</th>
                  </tr>
                </thead>
                <tbody>
                  {s.rows.map((row) => (
                    <tr key={row.seq}>
                      <td>{row.seq}</td>
                      <td title={row.ts}>{whenText(row.ts)}</td>
                      <td>{row.actor}</td>
                      <td><code>{row.verb}</code></td>
                      <td><StatusBadge value={row.status} glossary={AUDIT_STATUS} /></td>
                      <td>{row.run_id ? <RunLink runId={row.run_id} /> : <code>-</code>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {s.exported !== null && <CodeBlock value={s.exported} />}
    </div>
  );
}
