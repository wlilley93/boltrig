// Round Three evaluation harness (Epic EVAL). Create a case, run it (the runner
// spawns the target through the kernel chokepoint under the INITIATOR's grants,
// so an eval can never call a verb the initiator lacks - SEC-29), and list runs.
// A run shows passed + the child's effective_grants, which is the no-escalation
// evidence: e.g. an assertion {"forbidden_grants":["ticket.create"]} passes only
// if that grant is absent from effective_grants.

import { useState } from "react";

import { api } from "../api/client";
import type { EvalRunResult, EvalRunSummary } from "../api/types";
import { useFetch } from "../useFetch";
import { CodeBlock, GrantList, csvToList, errText, parseJson } from "./shared";

export function EvalPanel() {
  const [caseId, setCaseId] = useState("");
  const [targetKind, setTargetKind] = useState<"skill" | "workflow">("skill");
  const [targetRef, setTargetRef] = useState("");
  const [input, setInput] = useState("{}");
  const [assertions, setAssertions] = useState(
    '{"forbidden_grants": ["ticket.create"]}',
  );
  const [labels, setLabels] = useState("");
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [createMsg, setCreateMsg] = useState<string | null>(null);

  const [runId, setRunId] = useState("");
  const [runBusy, setRunBusy] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [runResult, setRunResult] = useState<EvalRunResult | null>(null);

  const [filterCase, setFilterCase] = useState("");
  const runs = useFetch(
    () => api.evalRuns(filterCase.trim() || undefined),
    [filterCase],
  );

  async function createCase() {
    if (!targetRef.trim()) {
      setCreateError("target_ref is required.");
      return;
    }
    let parsedInput: Record<string, unknown>;
    let parsedAssertions: Record<string, unknown>;
    try {
      parsedInput = parseJson<Record<string, unknown>>(input, {});
      parsedAssertions = parseJson<Record<string, unknown>>(assertions, {});
    } catch (err) {
      setCreateError(errText(err));
      return;
    }
    setCreateBusy(true);
    setCreateError(null);
    setCreateMsg(null);
    try {
      const res = await api.createEvalCase({
        id: caseId.trim() || undefined,
        target_kind: targetKind,
        target_ref: targetRef.trim(),
        input: parsedInput,
        assertions: parsedAssertions,
        labels: csvToList(labels),
      });
      if (res.status === "ok") {
        setCreateMsg(`Created case ${res.id}.`);
        if (res.id) setRunId(res.id);
        runs.reload();
      } else {
        setCreateError(`${res.status}: ${res.reason ?? "rejected"}`);
      }
    } catch (err) {
      setCreateError(errText(err));
    } finally {
      setCreateBusy(false);
    }
  }

  async function run() {
    if (!runId.trim()) {
      setRunError("case_id is required.");
      return;
    }
    setRunBusy(true);
    setRunError(null);
    setRunResult(null);
    try {
      const res = await api.runEval({ case_id: runId.trim() });
      if (res.error) setRunError(res.error);
      else {
        setRunResult(res);
        runs.reload();
      }
    } catch (err) {
      setRunError(errText(err));
    } finally {
      setRunBusy(false);
    }
  }

  const runList: EvalRunSummary[] = runs.data?.runs ?? [];

  return (
    <section className="panel">
      <div className="panel__head">
        <h2>Eval</h2>
        <div className="panel__actions">
          <span className="muted">no-escalation harness</span>
        </div>
      </div>

      <div className="cols">
        <div className="stack">
          <div className="form">
            <div className="form__title">Create case</div>
            <div className="form__grid">
              <label className="field">
                <span>id (optional)</span>
                <input
                  value={caseId}
                  onChange={(e) => setCaseId(e.target.value)}
                />
              </label>
              <label className="field">
                <span>target_kind</span>
                <select
                  value={targetKind}
                  onChange={(e) =>
                    setTargetKind(
                      e.target.value === "workflow" ? "workflow" : "skill",
                    )
                  }
                >
                  <option value="skill">skill</option>
                  <option value="workflow">workflow</option>
                </select>
              </label>
              <label className="field">
                <span>target_ref</span>
                <input
                  value={targetRef}
                  onChange={(e) => setTargetRef(e.target.value)}
                />
              </label>
            </div>
            <label className="field">
              <span>input (JSON)</span>
              <textarea
                className="code"
                value={input}
                onChange={(e) => setInput(e.target.value)}
              />
            </label>
            <label className="field">
              <span>assertions (JSON)</span>
              <textarea
                className="code"
                value={assertions}
                onChange={(e) => setAssertions(e.target.value)}
              />
            </label>
            <label className="field">
              <span>labels (comma list)</span>
              <input
                value={labels}
                onChange={(e) => setLabels(e.target.value)}
              />
            </label>
            <div className="form__actions">
              <button
                className="btn btn--primary"
                disabled={createBusy}
                onClick={createCase}
              >
                {createBusy ? "..." : "Create case"}
              </button>
              {createMsg && <span className="ok">{createMsg}</span>}
              {createError && <span className="error">{createError}</span>}
            </div>
          </div>

          <div className="form">
            <div className="form__title">Run case</div>
            <div className="form__actions">
              <label className="field">
                <span>case_id</span>
                <input
                  value={runId}
                  onChange={(e) => setRunId(e.target.value)}
                />
              </label>
              <button className="btn btn--primary" disabled={runBusy} onClick={run}>
                {runBusy ? "..." : "Run"}
              </button>
              {runError && <span className="error">{runError}</span>}
            </div>
            {runResult && (
              <div className="stack">
                <div className="kv">
                  <span
                    className={`badge ${runResult.passed ? "badge--pass" : "badge--fail"}`}
                  >
                    {runResult.passed ? "passed" : "failed"}
                  </span>
                  {typeof runResult.score === "number" && (
                    <span className="badge">score {runResult.score}</span>
                  )}
                  {runResult.run_id && (
                    <code className="tag">{runResult.run_id}</code>
                  )}
                </div>
                <div className="row-line">
                  <span className="muted">effective_grants</span>
                  <GrantList grants={runResult.detail?.effective_grants} />
                </div>
                <CodeBlock value={runResult.detail ?? {}} />
              </div>
            )}
          </div>
        </div>

        <div className="list-card">
          <div className="list-card__head">
            <h3>Runs</h3>
            <div className="panel__actions">
              <label className="field">
                <span>filter case_id</span>
                <input
                  value={filterCase}
                  onChange={(e) => setFilterCase(e.target.value)}
                />
              </label>
              <button className="btn" onClick={() => runs.reload()}>
                Refresh
              </button>
            </div>
          </div>
          <div className="list-card__body">
            {runs.loading && !runs.data && <p className="muted">Loading...</p>}
            {runs.error && (
              <p className="error">Failed to load: {runs.error}</p>
            )}
            {!runs.loading && runList.length === 0 && (
              <p className="muted">No eval runs.</p>
            )}
            {runList.map((r) => (
              <div className="row-line" key={r.id}>
                <div>
                  <code>{r.case_id}</code>
                  <div className="muted">{r.run_id}</div>
                </div>
                <div className="kv">
                  <span
                    className={`badge ${r.passed ? "badge--pass" : "badge--fail"}`}
                  >
                    {r.passed ? "pass" : "fail"}
                  </span>
                  <span className="badge">score {r.score}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
