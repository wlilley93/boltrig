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

export function InsightPanel() {
  const cost = useFetch(() => api.cost(), []);
  const runs = useFetch(() => api.runs(), []);

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

  return (
    <section className="panel">
      <div className="panel__head">
        <h2>Insight</h2>
        <div className="panel__actions">
          <span className="muted">scope-filtered to your departments</span>
          <button
            className="btn"
            onClick={() => {
              cost.reload();
              runs.reload();
            }}
          >
            Refresh
          </button>
        </div>
      </div>

      <p className="notice">
        Every view here is filtered to the caller's visibility scope (SEC-33).
        Another department's runs and cost are not shown, so an empty result can
        simply mean nothing in your scope.
      </p>

      <div className="cols">
        <div className="list-card">
          <div className="list-card__head">
            <h3>Cost rollup</h3>
            <span className="muted">
              scope: {costData ? scopeLabel(costData.scope) : "..."}
            </span>
          </div>
          <div className="list-card__body">
            {cost.loading && !cost.data && <p className="muted">Loading...</p>}
            {cost.error && (
              <p className="error">Failed to load cost: {cost.error}</p>
            )}
            {costData && (
              <>
                <div className="row-line">
                  <span className="muted">total_cost_micros</span>
                  <strong>{costData.total_cost_micros}</strong>
                </div>
                {Object.entries(costData.by_actor).length === 0 ? (
                  <p className="muted">No cost recorded in scope.</p>
                ) : (
                  Object.entries(costData.by_actor).map(([who, micros]) => (
                    <div className="row-line" key={who}>
                      <code>{who}</code>
                      <span>{micros}</span>
                    </div>
                  ))
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
            {runs.error && (
              <p className="error">Failed to load runs: {runs.error}</p>
            )}
            {!runs.loading && runRows.length === 0 && (
              <p className="muted">No runs in scope.</p>
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
                  <span className="badge">{r.status}</span>
                  {r.owner && <span className="muted">{r.owner}</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="form">
        <div className="form__title">Audit search</div>
        <div className="form__actions">
          <label className="field">
            <span>actor</span>
            <input value={actor} onChange={(e) => setActor(e.target.value)} />
          </label>
          <label className="field">
            <span>verb</span>
            <input value={verb} onChange={(e) => setVerb(e.target.value)} />
          </label>
          <label className="field">
            <span>run id</span>
            <input value={run} onChange={(e) => setRun(e.target.value)} />
          </label>
          <button className="btn btn--primary" disabled={searchBusy} onClick={search}>
            {searchBusy ? "..." : "Search"}
          </button>
          <button className="btn" disabled={exportBusy} onClick={exportAudit}>
            {exportBusy ? "..." : "Export audit"}
          </button>
        </div>
        {searchError && <p className="error">{searchError}</p>}
        {exportError && <p className="error">Export: {exportError}</p>}

        {rows && (
          <>
            <p className="muted">
              {rows.length} result(s); scope: {searchScope || "all"}
            </p>
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>seq</th>
                    <th>ts</th>
                    <th>actor</th>
                    <th>verb</th>
                    <th>status</th>
                    <th>run_id</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.seq}>
                      <td>{row.seq}</td>
                      <td>{row.ts}</td>
                      <td>{row.actor}</td>
                      <td>
                        <code>{row.verb}</code>
                      </td>
                      <td>{row.status}</td>
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
          </>
        )}

        {exported !== null && <CodeBlock value={exported} />}
      </div>
    </section>
  );
}
