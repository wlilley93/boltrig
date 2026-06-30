// Round Three insight surface (Epic OBS). Cost rollup, audit search and a runs
// list - all scope-filtered server-side (SEC-33): a department-scoped caller
// only ever sees their own departments' runs. The copy makes that explicit so a
// viewer understands an empty result is scoping, not a bug. Audit export is
// gated to author/admin roles (a 403 renders as a denial).

import { useState } from "react";

import { api } from "../api/client";
import type { AuditRow, RunRow } from "../api/types";
import { useFetch } from "../useFetch";
import { CodeBlock, RunLink, errText, scopeLabel } from "./shared";
import {
  AUDIT_STATUS,
  FetchError,
  Field,
  Hint,
  PageIntro,
  Select,
  StatusBadge,
  WORK_STATUS,
} from "./ux";

// micros are millionths of a currency unit; show a readable amount, raw on hover.
function money(micros: number): string {
  return (micros / 1_000_000).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
}

function whenText(ts: string): string {
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? ts : d.toLocaleString();
}

function pct(spent: number, limit: number | null): number | null {
  if (!limit || limit <= 0) return null;
  return Math.min(100, Math.round((spent / limit) * 100));
}

function Budgets() {
  const budgets = useFetch(() => api.budgets(), []);
  const list = budgets.data?.budgets ?? [];
  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>Budgets</h3>
        <button className="btn" onClick={() => budgets.reload()}>
          Refresh
        </button>
      </div>
      <div className="list-card__body">
        {budgets.loading && !budgets.data && <p className="muted">Loading...</p>}
        <FetchError error={budgets.error} status={budgets.errorStatus} onRetry={budgets.reload} />
        {!budgets.loading && !budgets.error && list.length === 0 && (
          <p className="muted">No budgets set. Budgets cap token + cost spend per scope.</p>
        )}
        {list.map((b) => {
          const tp = pct(b.spent_tokens, b.token_limit);
          const cp = pct(b.spent_micros, b.cost_limit_micros);
          const worst = Math.max(tp ?? 0, cp ?? 0);
          return (
            <div className="budget-row" key={`${b.scope_type}:${b.id}`}>
              <div className="kv">
                <code className="tag">{b.scope_type}</code>
                <strong>{b.id}</strong>
                <span className="muted" style={{ fontSize: 11 }}>{b.window}</span>
                {b.hard_stop && (
                  <span className="badge badge--conseq-high" title="Spending stops at the limit.">
                    hard stop
                  </span>
                )}
              </div>
              <div
                className="budget-bar"
                title={`${worst}% of the tightest limit used`}
                role="progressbar"
                aria-valuenow={worst}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label={`${b.id} budget: ${worst}% used`}
              >
                <span
                  className={`budget-bar__fill ${worst >= 90 ? "is-down" : worst >= 70 ? "is-warn" : ""}`}
                  style={{ width: `${worst}%` }}
                />
              </div>
              <div className="kv" style={{ fontSize: 11 }}>
                {b.token_limit != null && (
                  <span className="muted">
                    tokens {b.spent_tokens.toLocaleString()} / {b.token_limit.toLocaleString()}
                  </span>
                )}
                {b.cost_limit_micros != null && (
                  <span className="muted">
                    cost {money(b.spent_micros)} / {money(b.cost_limit_micros)}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function InsightPanel() {
  const cost = useFetch(() => api.cost(), []);
  const runs = useFetch(() => api.runs(), []);
  const caps = useFetch(() => api.capabilities(), []);

  const [actor, setActor] = useState("");
  const [verb, setVerb] = useState("");
  const [run, setRun] = useState("");
  const [searchBusy, setSearchBusy] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [rows, setRows] = useState<AuditRow[] | null>(null);
  const [searchScope, setSearchScope] = useState<string>("");

  const [exported, setExported] = useState<unknown>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportBusy, setExportBusy] = useState(false);

  async function search() {
    setSearchBusy(true);
    setSearchError(null);
    try {
      const res = await api.auditSearch({
        actor: actor.trim() || undefined,
        verb: verb.trim() || undefined,
        run: run.trim() || undefined,
      });
      setRows(res.results);
      setSearchScope(scopeLabel(res.scope));
    } catch (err) {
      setSearchError(errText(err));
    } finally {
      setSearchBusy(false);
    }
  }

  async function exportAudit() {
    setExportBusy(true);
    setExportError(null);
    setExported(null);
    try {
      const res = await api.auditExport();
      if (res.error) setExportError(res.error);
      else setExported(res);
    } catch (err) {
      setExportError(errText(err));
    } finally {
      setExportBusy(false);
    }
  }

  const costData = cost.data;
  const runRows: RunRow[] = runs.data?.runs ?? [];
  const actorOptions = [
    { value: "", label: "Any actor" },
    ...Object.keys(costData?.by_actor ?? {}).map((a) => ({ value: a, label: a })),
  ];
  const verbOptions = [
    { value: "", label: "Any action" },
    ...(caps.data?.verbs ?? []).map((v) => ({ value: v.id, label: v.id })),
  ];

  return (
    <section className="panel">
      <PageIntro
        title="Insight"
        lead="See what your departments have been doing, what it cost, and search the full audit trail."
        how="Every number here is scoped to what you're allowed to see (SEC-33), so an empty result can simply mean nothing in your scope - not a bug."
        actions={
          <button
            className="btn"
            onClick={() => {
              cost.reload();
              runs.reload();
            }}
          >
            Refresh
          </button>
        }
      />

      <div className="cols">
        <div className="list-card">
          <div className="list-card__head">
            <h3>Cost</h3>
            <span className="muted">
              scope: {costData ? scopeLabel(costData.scope) : "..."}
            </span>
          </div>
          <div className="list-card__body">
            {cost.loading && !cost.data && <p className="muted">Loading...</p>}
            <FetchError error={cost.error} status={cost.errorStatus} onRetry={cost.reload} />
            {costData && (
              <>
                <div className="row-line">
                  <span className="muted">Total cost</span>
                  <strong title={`${costData.total_cost_micros} micros`}>
                    {money(costData.total_cost_micros)}
                  </strong>
                </div>
                {Object.entries(costData.by_actor).length === 0 ? (
                  <p className="muted">No cost recorded in scope yet.</p>
                ) : (
                  <>
                    <Hint>Who has spent what:</Hint>
                    {Object.entries(costData.by_actor).map(([who, micros]) => (
                      <div className="row-line" key={who}>
                        <code>{who}</code>
                        <span title={`${micros} micros`}>{money(micros)}</span>
                      </div>
                    ))}
                  </>
                )}
              </>
            )}
          </div>
        </div>

        <div className="list-card">
          <div className="list-card__head">
            <h3>Runs</h3>
            <span className="muted">{runRows.length}</span>
          </div>
          <div className="list-card__body">
            {runs.loading && !runs.data && <p className="muted">Loading...</p>}
            <FetchError error={runs.error} status={runs.errorStatus} onRetry={runs.reload} />
            {!runs.loading && runRows.length === 0 && (
              <p className="muted">No runs in your scope yet.</p>
            )}
            {runRows.map((r) => (
              <div className="row-line" key={r.work_item}>
                <div>
                  {r.run_id ? (
                    <RunLink runId={r.run_id} />
                  ) : (
                    <code className="muted">no run</code>
                  )}
                  <div className="muted">{r.intent}</div>
                </div>
                <div className="kv">
                  <StatusBadge value={r.status} glossary={WORK_STATUS} />
                  {r.owner && <span className="muted">{r.owner}</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
        <Budgets />
      </div>

      <div className="form">
        <div className="form__title">Audit search</div>
        <Hint>
          Search the tamper-evident log of every governed action. Results are
          limited to your scope.
        </Hint>
        <div className="form__grid">
          <Field label="Actor" hint="Who performed the action.">
            <Select value={actor} ariaLabel="Actor" onChange={setActor} options={actorOptions} />
          </Field>
          <Field label="Action" hint="The verb that was called.">
            <Select value={verb} ariaLabel="Action" onChange={setVerb} options={verbOptions} />
          </Field>
          <Field label="Run id" hint="Paste a run id to see only its events." example="run_5f3a...">
            <input value={run} onChange={(e) => setRun(e.target.value)} />
          </Field>
        </div>
        <div className="form__actions">
          <button className="btn btn--primary" disabled={searchBusy} onClick={search}>
            {searchBusy ? "Searching..." : "Search"}
          </button>
          <button className="btn" disabled={exportBusy} onClick={exportAudit} title="Download the full audit log as a file - available to authors and admins.">
            {exportBusy ? "Exporting..." : "Export audit"}
          </button>
        </div>
        {searchError && <p className="error">{searchError}</p>}
        {exportError && <p className="notice warn">Export: {exportError}</p>}

        {rows && (
          <>
            <p className="muted">
              {rows.length === 0
                ? "No audit events match - try clearing a filter (results are limited to your scope)."
                : `${rows.length} result(s); scope: ${searchScope || "all"}`}
            </p>
            {rows.length > 0 && (
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
                    {rows.map((row) => (
                      <tr key={row.seq}>
                        <td>{row.seq}</td>
                        <td title={row.ts}>{whenText(row.ts)}</td>
                        <td>{row.actor}</td>
                        <td>
                          <code>{row.verb}</code>
                        </td>
                        <td>
                          <StatusBadge value={row.status} glossary={AUDIT_STATUS} />
                        </td>
                        <td>
                          {row.run_id ? (
                            <RunLink runId={row.run_id} />
                          ) : (
                            <code>-</code>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}

        {exported !== null && <CodeBlock value={exported} />}
      </div>
    </section>
  );
}
