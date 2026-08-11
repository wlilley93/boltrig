import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BoltrigApiError,
  type CreateEvalCaseRequest,
  type EvalCaseItem,
  type EvalCaseLifecycleResponse,
  type EvalRunResult,
  type EvalRunSummary,
  type EvalTargetKind,
  type StatusAck,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import { useRouteSelection } from "../useRouteSelection";
import {
  ExactApprovalFinalizer,
  governedResultReason,
  type GovernedResult,
  useExactApprovalFinalizer,
} from "./ExactApprovalFinalizer";
import { Topbar, Unavailable } from "./Shell";

type SurfaceState = "loading" | "ready" | "denied" | "unavailable";
type Notice = { text: string; error?: boolean };

interface CaseDraft {
  id: string;
  targetKind: EvalTargetKind;
  targetRef: string;
  input: string;
  assertions: string;
  labels: string;
}

const blankCase: CaseDraft = {
  id: "",
  targetKind: "skill",
  targetRef: "",
  input: "{\n  \"task\": \"\"\n}",
  assertions: "{\n  \"must_not_call\": []\n}",
  labels: "",
};

type ExactEvalMutation =
  | { kind: "save"; body: CreateEvalCaseRequest }
  | {
      kind: "lifecycle";
      caseId: string;
      action: "archive" | "restore";
    };

interface ExactEvalResult extends GovernedResult {
  value?: StatusAck | EvalCaseLifecycleResponse;
}

export function EvaluationsView() {
  const [selectedId, setSelectedId] = useRouteSelection("evaluations");
  const [cases, setCases] = useState<EvalCaseItem[]>([]);
  const [runs, setRuns] = useState<EvalRunSummary[]>([]);
  const [surfaceState, setSurfaceState] = useState<SurfaceState>("loading");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<CaseDraft>(blankCase);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState<Notice | null>(null);
  const [historyError, setHistoryError] = useState("");
  const [lastResult, setLastResult] = useState<EvalRunResult | null>(null);
  const exactApprovalInvalidator = useRef<() => void>(() => undefined);

  const selected = cases.find((item) => item.id === selectedId) ?? null;
  const selectedRuns = useMemo(
    () => selectedId ? runs.filter((run) => run.case_id === selectedId) : runs,
    [runs, selectedId],
  );
  const activeCount = cases.filter((item) => item.is_active).length;

  const invalidateExactApproval = useCallback(() => {
    exactApprovalInvalidator.current();
  }, []);

  const exactApproval = useExactApprovalFinalizer<
    ExactEvalMutation,
    ExactEvalResult
  >({
    isCurrent: (mutation) => {
      if (mutation.kind === "save") {
        if (!editing) return false;
        try {
          return routeInputEquals(mutation.body, evalCaseRequest(draft));
        } catch {
          return false;
        }
      }
      const current = cases.find((item) => item.id === mutation.caseId);
      return selectedId === mutation.caseId
        && current !== undefined
        && current.is_active === (mutation.action === "archive");
    },
    replay: async (mutation, approvalId) => {
      const result = mutation.kind === "save"
        ? await client.createEvalCase(mutation.body, approvalId)
        : mutation.action === "archive"
          ? await client.archiveEvalCase(mutation.caseId, approvalId)
          : await client.restoreEvalCase(mutation.caseId, approvalId);
      return normalizeEvalResult(result);
    },
    onApplied: async (result, mutation) => {
      if (mutation.kind === "save") {
        setEditing(false);
        setNotice({
          text: "Evaluation case saved through the exact approved authoring route.",
        });
        const value = result.value as StatusAck | undefined;
        await refreshCases(
          typeof value?.id === "string"
            ? value.id
            : mutation.body.id ?? null,
        );
        return;
      }
      setNotice({
        text: mutation.action === "archive"
          ? "Evaluation case archived. Its fixture and run history remain available."
          : "Evaluation case restored and available to run.",
      });
      await refreshCases(mutation.caseId);
    },
    onRefused: (result) => {
      setNotice({
        text: governedResultReason(
          result, "The exact approved evaluation change was refused.",
        ),
        error: true,
      });
    },
  });
  exactApprovalInvalidator.current = exactApproval.invalidate;

  async function loadHistory() {
    invalidateExactApproval();
    setHistoryError("");
    try {
      setRuns((await client.evalRuns()).runs);
    } catch (error) {
      setHistoryError(apiMessage(error, "Evaluation history is unavailable."));
    }
  }

  async function refreshCases(preferredId = selectedId) {
    invalidateExactApproval();
    setSurfaceState("loading");
    try {
      const result = await client.evalCases();
      setCases(result.cases);
      setSelectedId(result.cases.some((item) => item.id === preferredId) ? preferredId : null);
      setSurfaceState("ready");
      await loadHistory();
    } catch (error) {
      setCases([]);
      setSelectedId(null);
      if (error instanceof BoltrigApiError && error.status === 403) {
        setSurfaceState("denied");
        setNotice({ text: "Evaluation fixtures are restricted to authors and administrators.", error: true });
      } else {
        setSurfaceState("unavailable");
      }
    }
  }

  useEffect(() => {
    void refreshCases(selectedId);
  }, []);

  function newCase() {
    invalidateExactApproval();
    setDraft(blankCase);
    setEditing(true);
    setNotice(null);
  }

  function editCase(item: EvalCaseItem) {
    invalidateExactApproval();
    setDraft({
      id: item.id,
      targetKind: item.target_kind,
      targetRef: item.target_ref,
      input: JSON.stringify(item.input, null, 2),
      assertions: JSON.stringify(item.assertions, null, 2),
      labels: item.labels.join(", "),
    });
    setEditing(true);
    setNotice(null);
  }

  async function saveCase() {
    let body: CreateEvalCaseRequest;
    try {
      body = evalCaseRequest(draft);
    } catch (error) {
      setNotice({ text: error instanceof Error ? error.message : "Case JSON is invalid.", error: true });
      return;
    }
    const mutation: ExactEvalMutation = { kind: "save", body };
    setBusy("save");
    setNotice(null);
    try {
      const result = await client.createEvalCase(mutation.body);
      if (result.status === "ok") {
        setEditing(false);
        setNotice({ text: "Evaluation case saved through the governed authoring route." });
        await refreshCases(typeof result.id === "string" ? result.id : body.id ?? null);
      } else if (result.status === "pending_human") {
        exactApproval.begin(
          mutation, result, "Evaluation fixture save",
        );
        setNotice({ text: "This evaluation case is waiting for human approval in the originating chat." });
      } else {
        setNotice({ text: result.reason ?? "The evaluation case was refused.", error: true });
      }
    } catch (error) {
      setNotice({ text: apiMessage(error, "Evaluation authoring is unavailable."), error: true });
    } finally {
      setBusy("");
    }
  }

  async function runCase(item: EvalCaseItem) {
    if (!item.is_active) {
      setNotice({ text: "Restore this evaluation case before running it.", error: true });
      return;
    }
    setBusy(`run:${item.id}`);
    setNotice(null);
    setLastResult(null);
    try {
      const result = await client.runEval({ case_id: item.id });
      if (result.error) {
        setNotice({ text: readableCode(result.error), error: true });
      } else {
        setLastResult(result);
        setNotice({
          text: result.passed
            ? `Evaluation passed with ${percent(result.score)} score.`
            : `Evaluation completed but failed with ${percent(result.score)} score.`,
          error: result.passed === false,
        });
        await loadHistory();
      }
    } catch (error) {
      setNotice({ text: apiMessage(error, "The evaluation could not run."), error: true });
    } finally {
      setBusy("");
    }
  }

  async function setCaseLifecycle(item: EvalCaseItem) {
    const action = item.is_active ? "archive" : "restore";
    const mutation: ExactEvalMutation = {
      kind: "lifecycle",
      caseId: item.id,
      action,
    };
    setBusy(`lifecycle:${item.id}`);
    setNotice(null);
    try {
      const result = item.is_active
        ? await client.archiveEvalCase(item.id)
        : await client.restoreEvalCase(item.id);
      if (result.status === "ok") {
        setNotice({
          text: action === "archive"
            ? "Evaluation case archived. Its fixture and run history remain available."
            : "Evaluation case restored and available to run.",
        });
        await refreshCases(item.id);
      } else if (result.status === "pending_human") {
        exactApproval.begin(
          mutation,
          result,
          action === "archive"
            ? "Evaluation fixture archive"
            : "Evaluation fixture restore",
        );
        setNotice({
          text: `This evaluation ${action} is waiting for human approval in the originating chat.`,
        });
      } else {
        setNotice({
          text: readableCode(result.reason ?? `eval_case_${action}_failed`),
          error: true,
        });
      }
    } catch (error) {
      setNotice({
        text: apiMessage(error, `The evaluation case could not be ${action}d.`),
        error: true,
      });
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="page">
      <Topbar
        title="Evaluations"
        status={surfaceState === "ready"
          ? `${activeCount} active · ${cases.length - activeCount} archived · ${runs.length} runs`
          : stateLabel(surfaceState)}
      />
      <div className="page-content">
        <div className="page-intro">
          <div>
            <h2>Test governed agent behavior</h2>
            <p>Evaluation runs use the caller’s grant ceiling and record durable verdicts. A test never grants its target authority the author does not hold.</p>
          </div>
          {surfaceState === "ready" && (
            <button className="primary-button" onClick={newCase}>New evaluation</button>
          )}
        </div>
        {notice && <p className="notice eval-notice" role={notice.error ? "alert" : "status"}>{notice.text}</p>}
        <ExactApprovalFinalizer controller={exactApproval} />
        {surfaceState === "loading" && <Unavailable title="Loading evaluations">Checking access to governed evaluation fixtures.</Unavailable>}
        {surfaceState === "denied" && <Unavailable title="Evaluation access denied">Your current role cannot view sensitive fixtures or author evaluation cases.</Unavailable>}
        {surfaceState === "unavailable" && <Unavailable title="Evaluations unavailable">The evaluation service could not be reached.</Unavailable>}
        {surfaceState === "ready" && editing && (
          <CaseEditor
            draft={draft}
            busy={busy === "save"}
            onDraft={(value) => {
              invalidateExactApproval();
              setDraft(value);
            }}
            onCancel={() => {
              invalidateExactApproval();
              setEditing(false);
            }}
            onSave={() => void saveCase()}
          />
        )}
        {surfaceState === "ready" && (
          <div className={selected ? "split-view detail-open" : "split-view"}>
            <section className="data-list" aria-label="Evaluation cases">
              {cases.length === 0
                ? <Unavailable title="No evaluation cases">Create a scoped fixture to establish the first repeatable check.</Unavailable>
                : cases.map((item) => {
                  const latest = runs.find((run) => run.case_id === item.id);
                  return (
                    <button
                      className={selectedId === item.id ? "data-row selected" : "data-row"}
                      key={item.id}
                      onClick={() => {
                        invalidateExactApproval();
                        setSelectedId(item.id);
                        setLastResult(null);
                      }}
                    >
                      <span className={`activity-dot ${item.is_active && latest ? (latest.passed ? "ok" : "failed") : "paused"}`} />
                      <span className="data-row-copy">
                        <strong>{item.id}</strong>
                        <small>{item.target_kind} · {item.target_ref}</small>
                      </span>
                      <span className="row-meta">
                        {!item.is_active
                          ? `archived${latest ? ` · ${percent(latest.score)} ${latest.passed ? "pass" : "fail"}` : ""}`
                          : latest
                            ? `${percent(latest.score)} · ${latest.passed ? "pass" : "fail"}`
                            : "not run"}
                      </span>
                    </button>
                  );
                })}
            </section>
            {selected && (
              <aside className="detail-panel eval-detail" aria-label={`${selected.id} evaluation`}>
                <div className="detail-heading">
                  <div><p className="eyebrow">Evaluation case</p><h3>{selected.id}</h3></div>
                  <button className="icon-button" aria-label="Close evaluation details" onClick={() => setSelectedId(null)}>×</button>
                </div>
                <dl className="fact-grid">
                  <div><dt>Target kind</dt><dd>{selected.target_kind}</dd></div>
                  <div><dt>Target</dt><dd>{selected.target_ref}</dd></div>
                  <div><dt>Labels</dt><dd>{selected.labels.join(", ") || "None"}</dd></div>
                  <div><dt>Runs</dt><dd>{selectedRuns.length}</dd></div>
                  <div><dt>Status</dt><dd>{selected.status}</dd></div>
                </dl>
                <div className="inline-actions eval-actions">
                  <button
                    className="primary-button"
                    disabled={busy !== "" || !selected.is_active}
                    title={selected.is_active ? undefined : "Restore this case before running it"}
                    onClick={() => void runCase(selected)}
                  >
                    {busy === `run:${selected.id}` ? "Running…" : "Run evaluation"}
                  </button>
                  <button className="secondary-button" disabled={busy !== ""} onClick={() => editCase(selected)}>Edit case</button>
                  <button
                    className="secondary-button"
                    disabled={busy !== ""}
                    onClick={() => void setCaseLifecycle(selected)}
                  >
                    {busy === `lifecycle:${selected.id}`
                      ? selected.is_active ? "Archiving…" : "Restoring…"
                      : selected.is_active ? "Archive case" : "Restore case"}
                  </button>
                </div>
                {lastResult && <ResultCard result={lastResult} />}
                <details className="fixture-details">
                  <summary>Fixture input and assertions</summary>
                  <p className="eyebrow">Input</p><pre>{JSON.stringify(selected.input, null, 2)}</pre>
                  <p className="eyebrow">Assertions</p><pre>{JSON.stringify(selected.assertions, null, 2)}</pre>
                </details>
                <section className="detail-section">
                  <div className="section-heading"><p className="eyebrow">Run history</p><button className="icon-button" aria-label="Refresh evaluation history" onClick={() => void loadHistory()}>↻</button></div>
                  {historyError && <p className="muted small" role="status">{historyError}</p>}
                  {!historyError && selectedRuns.length === 0 && <p className="muted small">This case has not run.</p>}
                  {selectedRuns.map((run) => (
                    <div className="eval-run-row" key={run.id}>
                      <span className={`activity-dot ${run.passed ? "ok" : "failed"}`} />
                      <span>
                        <strong>{run.passed ? "Passed" : "Failed"}</strong>
                        <small>{run.id}{run.run_id ? ` · run ${run.run_id}` : ""}</small>
                        <small>
                          {run.target_kind && run.target_ref
                            ? `${run.target_kind} · ${run.target_ref}`
                            : "Target was not recorded for this legacy run"}
                        </small>
                        <details className="fixture-details eval-run-details">
                          <summary>Run details</summary>
                          {run.detail
                            ? <pre>{JSON.stringify(run.detail, null, 2)}</pre>
                            : <p className="muted small">Verdict detail was not recorded for this legacy run.</p>}
                        </details>
                      </span>
                      <span className="row-meta">{percent(run.score)}</span>
                    </div>
                  ))}
                </section>
              </aside>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function CaseEditor({
  draft,
  busy,
  onDraft,
  onCancel,
  onSave,
}: {
  draft: CaseDraft;
  busy: boolean;
  onDraft(draft: CaseDraft): void;
  onCancel(): void;
  onSave(): void;
}) {
  return (
    <form className="admin-form eval-editor" aria-label="Evaluation case editor" onSubmit={(event) => { event.preventDefault(); onSave(); }}>
      <div className="admin-form-heading">
        <div><p className="eyebrow">{draft.id ? "Edit fixture" : "New fixture"}</p><h3>{draft.id || "Create evaluation case"}</h3></div>
        <button className="icon-button" type="button" aria-label="Close evaluation editor" onClick={onCancel}>×</button>
      </div>
      <div className="admin-fields three">
        <label><span>Case ID (optional)</span><input className="field-control" value={draft.id} onChange={(event) => onDraft({ ...draft, id: event.target.value })} /></label>
        <label>
          <span>Target kind</span>
          <select
            className="field-control"
            required
            value={draft.targetKind}
            onChange={(event) => onDraft({
              ...draft,
              targetKind: event.target.value as EvalTargetKind,
            })}
          >
            <option value="skill">Skill</option>
            <option value="workflow">Workflow</option>
          </select>
        </label>
        <label><span>Target reference</span><input className="field-control" required value={draft.targetRef} onChange={(event) => onDraft({ ...draft, targetRef: event.target.value })} /></label>
      </div>
      <label><span>Labels (comma separated)</span><input className="field-control" value={draft.labels} onChange={(event) => onDraft({ ...draft, labels: event.target.value })} /></label>
      <div className="admin-fields">
        <label><span>Input (JSON object)</span><textarea className="field-control code-field" rows={8} value={draft.input} onChange={(event) => onDraft({ ...draft, input: event.target.value })} /></label>
        <label><span>Assertions (JSON object)</span><textarea className="field-control code-field" rows={8} value={draft.assertions} onChange={(event) => onDraft({ ...draft, assertions: event.target.value })} /></label>
      </div>
      <div className="inline-actions">
        <button className="primary-button" disabled={busy}>{busy ? "Saving…" : "Save case"}</button>
        <button className="secondary-button" type="button" disabled={busy} onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

function ResultCard({ result }: { result: EvalRunResult }) {
  const checks = Object.entries(result.detail?.checks ?? {});
  return (
    <section className={`eval-result ${result.passed ? "passed" : "failed"}`} aria-label="Latest evaluation result">
      <div><p className="eyebrow">Latest result</p><strong>{result.passed ? "Passed" : "Failed"} · {percent(result.score)}</strong></div>
      {result.run_id && <small>Run {result.run_id}</small>}
      {checks.length > 0 && <ul>{checks.map(([name, passed]) => <li key={name}>{passed ? "✓" : "×"} {name}</li>)}</ul>}
      {result.detail?.target_error && <p>Target error: {result.detail.target_error}</p>}
    </section>
  );
}

function evalCaseRequest(draft: CaseDraft): CreateEvalCaseRequest {
  if (!draft.targetRef.trim()) {
    throw new Error("Target kind and target reference are required.");
  }
  return {
    ...(draft.id.trim() ? { id: draft.id.trim() } : {}),
    target_kind: draft.targetKind,
    target_ref: draft.targetRef.trim(),
    input: parseObject(draft.input, "Input"),
    assertions: parseObject(draft.assertions, "Assertions"),
    labels: draft.labels
      .split(",")
      .map((label) => label.trim())
      .filter(Boolean),
  };
}

function normalizeEvalResult<T extends GovernedResult>(
  result: T,
): ExactEvalResult {
  return {
    status: result.status,
    hitl_request_id: result.hitl_request_id,
    reason: result.reason,
    value: result as ExactEvalResult["value"],
  };
}

function routeInputEquals(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function parseObject(value: string, label: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} must be a JSON object.`);
  }
  return parsed as Record<string, unknown>;
}

function apiMessage(error: unknown, fallback: string): string {
  if (!(error instanceof BoltrigApiError)) return fallback;
  if (error.status === 403) return "Your current role is not permitted to perform this evaluation action.";
  const body = error.body;
  if (body && typeof body === "object") {
    const value = (body as { reason?: unknown; error?: unknown }).reason
      ?? (body as { error?: unknown }).error;
    if (typeof value === "string") return readableCode(value);
  }
  return fallback;
}

function readableCode(value: string): string {
  if (value === "eval_unavailable") return "Evaluation execution is not enabled on this deployment.";
  if (value === "no_such_case") return "This evaluation case no longer exists.";
  if (value === "eval_case_archived") return "Restore this evaluation case before running it.";
  return value.replaceAll("_", " ");
}

function percent(value?: number): string {
  return `${Math.round((value ?? 0) * 100)}%`;
}

function stateLabel(state: SurfaceState) {
  if (state === "loading") return "Checking access";
  if (state === "denied") return "Author only";
  if (state === "unavailable") return "Unavailable";
  return "";
}
