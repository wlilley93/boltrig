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
        <Field label="Stream" hint="Governed actions or security events.">
          <Select
            value={s.stream}
            ariaLabel="Stream"
            onChange={(value) => s.setStream(value as "audit" | "security")}
            options={[
              { value: "audit", label: "Audit actions" },
              { value: "security", label: "Security events" },
            ]}
          />
        </Field>
        <Field label="Actor" hint="Who performed the action.">
          <Select value={s.actor} ariaLabel="Actor" onChange={s.setActor} options={s.actorOptions} />
        </Field>
        <Field label="Action" hint="The verb that was called.">
          <Select value={s.verb} ariaLabel="Action" onChange={s.setVerb} options={s.verbOptions} />
        </Field>
        <Field label="Run id" hint="Paste a run id to see only its events." example="run_5f3a...">
          <input aria-label="Run id" value={s.run} onChange={(e) => s.setRun(e.target.value)} disabled={s.stream === "security"} />
        </Field>
        <Field label="Resource" hint="Resource kind, such as ticket or auth.login.">
          <input aria-label="Resource" value={s.resource} onChange={(e) => s.setResource(e.target.value)} />
        </Field>
        <Field label="Status" hint="Server-side outcome filter.">
          <Select
            value={s.status}
            ariaLabel="Status"
            onChange={s.setStatus}
            disabled={s.stream === "security"}
            options={[
              { value: "", label: "Any status" },
              { value: "ok", label: "OK" },
              { value: "error", label: "Error" },
              { value: "failed", label: "Failed" },
              { value: "denied", label: "Denied" },
              { value: "pending", label: "Pending" },
            ]}
          />
        </Field>
        <Field label="From" hint="Inclusive start date.">
          <input aria-label="From" type="date" value={s.since} onChange={(e) => s.setSince(e.target.value)} />
        </Field>
        <Field label="Through" hint="Inclusive end date.">
          <input aria-label="Through" type="date" value={s.until} onChange={(e) => s.setUntil(e.target.value)} />
        </Field>
        {s.stream === "security" && (
          <Field label="Event type" hint="Optional exact security event type.">
            <input aria-label="Event type" value={s.eventType} onChange={(e) => s.setEventType(e.target.value)} placeholder="login_failure" />
          </Field>
        )}
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
                    <th>{s.stream === "security" ? "Event" : "Action"}</th>
                    <th>{s.stream === "security" ? "Reason" : "Status"}</th>
                    <th>Run</th>
                    <th>Details</th>
                  </tr>
                </thead>
                <tbody>
                  {s.rows.map((row) => (
                    <tr key={row.seq}>
                      <td>{row.seq}</td>
                      <td title={row.ts}>{whenText(row.ts)}</td>
                      <td>{row.actor}</td>
                      <td><code>{row.event_type ?? row.verb ?? "-"}</code></td>
                      <td>
                        {row.status
                          ? <StatusBadge value={row.status} glossary={AUDIT_STATUS} />
                          : <span>{row.reason || "-"}</span>}
                      </td>
                      <td>{row.run_id ? <RunLink runId={row.run_id} /> : <code>-</code>}</td>
                      <td>
                        <details>
                          <summary>Inspect</summary>
                          <CodeBlock value={row} />
                        </details>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {s.exported !== null && (
        <p className="notice good" role="status">
          Downloaded {s.exported.count ?? s.exported.events?.length ?? 0} audit event(s) as JSON.
        </p>
      )}
    </div>
  );
}
