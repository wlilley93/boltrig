// Round Three evaluation harness (Epic EVAL). Create a case, run it (the runner
// spawns the target through the kernel chokepoint under the INITIATOR's grants,
// so an eval can never call a verb the initiator lacks - SEC-29), and list runs.
// A run shows passed + the child's effective_grants, which is the no-escalation
// evidence: e.g. an assertion {"forbidden_grants":["ticket.create"]} passes only
// if that grant is absent from effective_grants.

import { useMemo, useState } from "react";

import { api } from "../api/client";
import type { EvalRunResult, EvalRunSummary } from "../api/types";
import { useFetch } from "../useFetch";
import { CodeBlock, GrantList, csvToList, errText, parseJson } from "./shared";
import { EmptyState, Field, Hint, InfoCallout, PageIntro, Select } from "./ux";
import { SegmentedV2 } from "./uxForm";

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

  // live option sources: targets (skills / workflows), verbs (forbidden grants).
  const skills = useFetch(() => api.skills(), []);
  const workflows = useFetch(() => api.workflows(), []);
  const caps = useFetch(() => api.capabilities(), []);

  const targetOptions = useMemo(() => {
    const ids =
      targetKind === "skill"
        ? (skills.data?.skills ?? []).map((s) => s.id)
        : (workflows.data?.workflows ?? []).map((w) => w.id);
    return [{ value: "", label: `Choose a ${targetKind}...` }, ...ids.map((id) => ({ value: id, label: id }))];
  }, [targetKind, skills.data, workflows.data]);

  const verbs = caps.data?.verbs ?? [];

  // the forbidden-grants set is derived from (and written back to) the assertions
  // JSON, so the guided chips and the raw JSON never disagree.
  const forbidden = useMemo(() => {
    try {
      const o = parseJson<{ forbidden_grants?: unknown }>(assertions, {});
      return Array.isArray(o.forbidden_grants) ? (o.forbidden_grants as string[]) : [];
    } catch {
      return [];
    }
  }, [assertions]);

  function toggleForbidden(verbId: string) {
    if (!verbId) return;
    let o: Record<string, unknown>;
    try {
      o = parseJson<Record<string, unknown>>(assertions, {});
    } catch {
      o = {};
    }
    const list = Array.isArray(o.forbidden_grants) ? (o.forbidden_grants as string[]) : [];
    const next = list.includes(verbId) ? list.filter((x) => x !== verbId) : [...list, verbId];
    setAssertions(JSON.stringify({ ...o, forbidden_grants: next }, null, 2));
  }

  const caseIdOptions = useMemo(() => {
    const ids = new Set<string>();
    for (const r of runs.data?.runs ?? []) if (r.case_id) ids.add(r.case_id);
    if (runId) ids.add(runId);
    return [{ value: "", label: "Choose a case..." }, ...[...ids].map((id) => ({ value: id, label: id }))];
  }, [runs.data, runId]);

  async function createCase() {
    if (!targetRef.trim()) {
      setCreateError("Pick a skill or workflow to test first.");
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
        setCreateMsg(`Created case ${res.id}. It's selected below - run it next.`);
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
      setRunError("Pick a case to run first.");
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
      <PageIntro
        title="Eval"
        lead="Test that a skill or workflow does the right thing - and only uses the permissions it's supposed to."
        how="1. Create a case (what to run + what to assert). 2. Run it. 3. Review pass/fail with the permissions the run actually had. The test runs under your permissions, so it can never exceed them."
      />

      <div className="cols">
        <div className="stack">
          <div className="form">
            <div className="form__title">1. Create a case</div>
            <div className="form__grid">
              <Field label="Test" hint="Is the thing under test a skill or a workflow?">
                <SegmentedV2
                  value={targetKind}
                  ariaLabel="Target kind"
                  onChange={(v) => {
                    setTargetKind(v === "workflow" ? "workflow" : "skill");
                    setTargetRef("");
                  }}
                  options={[
                    { value: "skill", label: "A skill" },
                    { value: "workflow", label: "A workflow" },
                  ]}
                />
              </Field>
              <Field label="Which one" hint="The skill or workflow this case runs.">
                <Select
                  value={targetRef}
                  ariaLabel="Target"
                  onChange={setTargetRef}
                  options={targetOptions}
                />
              </Field>
              <Field
                label="Case id"
                hint="Leave blank to auto-generate. Set one to overwrite an existing case."
              >
                <input value={caseId} onChange={(e) => setCaseId(e.target.value)} />
              </Field>
            </div>

            <Field
              label="Input"
              hint="The input passed to the skill or workflow under test, as JSON."
              example='{"ticket_id": "4821"}'
            >
              <textarea
                className="code"
                value={input}
                onChange={(e) => setInput(e.target.value)}
              />
            </Field>

            <Field
              label="Permissions the run must NOT use"
              hint="The case passes only if none of these appear in the run's actual permissions. This is the core safety check."
            >
              <div className="kv">
                {forbidden.length === 0 ? (
                  <span className="ux-hint">None set - add one below.</span>
                ) : (
                  forbidden.map((g) => (
                    <button
                      key={g}
                      type="button"
                      className="tag tag--accent"
                      title="Remove"
                      style={{ cursor: "pointer" }}
                      onClick={() => toggleForbidden(g)}
                    >
                      {g} x
                    </button>
                  ))
                )}
              </div>
              <Select
                value=""
                ariaLabel="Add a forbidden permission"
                onChange={toggleForbidden}
                options={[
                  { value: "", label: "Add a permission..." },
                  ...verbs.filter((v) => !forbidden.includes(v.id)).map((v) => ({ value: v.id, label: v.id })),
                ]}
              />
            </Field>

            <details>
              <summary className="ux-hint" style={{ cursor: "pointer" }}>
                Advanced: edit assertions as JSON
              </summary>
              <Field label="Assertions (JSON)" hint="The full assertion object. forbidden_grants is the supported key.">
                <textarea
                  className="code"
                  value={assertions}
                  onChange={(e) => setAssertions(e.target.value)}
                />
              </Field>
            </details>

            <Field label="Labels" hint="Tags to group cases." example="regression, security">
              <input value={labels} onChange={(e) => setLabels(e.target.value)} />
            </Field>

            <div className="form__actions">
              <button
                className="btn btn--primary"
                disabled={createBusy}
                onClick={createCase}
              >
                {createBusy ? "Creating..." : "Create case"}
              </button>
              {createMsg && <span className="ok">{createMsg}</span>}
              {createError && <span className="error">{createError}</span>}
            </div>
          </div>

          <div className="form">
            <div className="form__title">2. Run a case</div>
            <div className="form__actions">
              <Field label="Case" hint="Pick the case to run.">
                <Select value={runId} ariaLabel="Case to run" onChange={setRunId} options={caseIdOptions} />
              </Field>
              <button className="btn btn--primary" disabled={runBusy} onClick={run}>
                {runBusy ? "Running..." : "Run"}
              </button>
              {runError && <span className="error">{runError}</span>}
            </div>
            {runResult ? (
              <div className="stack">
                <div className="kv">
                  <span
                    className={`badge ${runResult.passed ? "badge--pass" : "badge--fail"}`}
                  >
                    {runResult.passed ? "passed" : "failed"}
                  </span>
                  {typeof runResult.score === "number" && (
                    <span className="badge" title="0 to 1">score {runResult.score}</span>
                  )}
                  {runResult.run_id && (
                    <code className="tag">{runResult.run_id}</code>
                  )}
                </div>
                <div className="row-line">
                  <span className="muted">Permissions the run actually used</span>
                  <GrantList grants={runResult.detail?.effective_grants} />
                </div>
                <CodeBlock value={runResult.detail ?? {}} />
              </div>
            ) : (
              <Hint>Run a case to see pass/fail and the permissions it used.</Hint>
            )}
          </div>
        </div>

        <div className="list-card">
          <div className="list-card__head">
            <h3>3. Runs</h3>
            <div className="panel__actions">
              <Field label="Filter by case">
                <Select
                  value={filterCase}
                  ariaLabel="Filter by case"
                  onChange={setFilterCase}
                  options={[{ value: "", label: "All cases" }, ...caseIdOptions.slice(1)]}
                />
              </Field>
              <button className="btn" onClick={() => runs.reload()}>
                Refresh
              </button>
            </div>
          </div>
          <div className="list-card__body">
            {runs.loading && !runs.data && <p className="muted">Loading...</p>}
            {runs.error && <p className="error">Could not load: {runs.error}</p>}
            {!runs.loading && runList.length === 0 && (
              <EmptyState
                title="No eval runs yet"
                body="Create and run a case to see results here."
              />
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
                  <span className="badge" title="0 to 1">score {r.score}</span>
                </div>
              </div>
            ))}
          </div>
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
