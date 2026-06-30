// Developer console (Capability plane). Surfaces three client-ready kernel
// endpoints that no other panel exposes: direct verb invoke (POST /v1/invoke),
// ephemeral agent spawn (POST /v1/spawn) and the generated adapter source
// (GET /v1/adapters/{id}/source). Every call is server-authoritative: a denial,
// a pending-human pause or a degraded result is rendered faithfully, exactly as
// the kernel returned it (the AdminPanel pattern). The role gate on the tab is
// cosmetic; the chokepoint is the real gate (a 403 returns a denial body).

import { useState } from "react";

import { api } from "../api/client";
import type {
  InvokeRequest,
  InvokeResult,
  SpawnRequest,
  SpawnResult,
} from "../api/types";
import { useFetch } from "../useFetch";
import {
  CodeBlock,
  GrantList,
  RunLink,
  csvToList,
  errText,
  parseJson,
} from "./shared";

// Read a run_id off an arbitrary result body without widening the typed unions:
// the kernel may carry it at the top level or inside `output`.
function pluckRunId(value: unknown): string | undefined {
  if (value && typeof value === "object" && "run_id" in value) {
    const id = (value as { run_id?: unknown }).run_id;
    if (typeof id === "string" && id) return id;
  }
  return undefined;
}

function runIdOf(value: unknown): string | undefined {
  const direct = pluckRunId(value);
  if (direct) return direct;
  if (value && typeof value === "object" && "output" in value) {
    return pluckRunId((value as { output?: unknown }).output);
  }
  return undefined;
}

// Render the InvokeResult union faithfully: ok / degraded show the output, a
// pending_human pause shows its HITL id, denied / error show the reason.
function InvokeResultView({ result }: { result: InvokeResult }) {
  const runId = runIdOf(result);
  return (
    <div className="stack">
      <div className="row-line">
        <span className="badge">{result.status}</span>
        {runId && <RunLink runId={runId} />}
      </div>
      {result.status === "ok" && <CodeBlock value={result.output} />}
      {result.status === "degraded" && (
        <>
          <p className="notice warn">
            Adapter degraded; the output below is best-effort.
          </p>
          <CodeBlock value={result.output} />
        </>
      )}
      {result.status === "pending_human" && (
        <p className="notice">
          Paused for a human (HITL request{" "}
          <code>{result.hitl_request_id}</code>). Resolve it in Approvals.
        </p>
      )}
      {result.status === "denied" && (
        <p className="error">denied: {result.reason}</p>
      )}
      {result.status === "error" && (
        <p className="error">error: {result.reason}</p>
      )}
    </div>
  );
}

export function DevConsolePanel() {
  // The scoped verb registry powers the invoke picker; the adapter inventory
  // powers the source viewer. Both are caller-scoped server-side.
  const caps = useFetch(() => api.capabilities(), []);
  const adapters = useFetch(() => api.adapters(), []);

  // --- Invoke a verb ---
  const [noun, setNoun] = useState("");
  const [verb, setVerb] = useState("");
  const [params, setParams] = useState("{}");
  const [invRun, setInvRun] = useState("");
  const [invContext, setInvContext] = useState("");
  const [invBusy, setInvBusy] = useState(false);
  const [invError, setInvError] = useState<string | null>(null);
  const [invResult, setInvResult] = useState<InvokeResult | null>(null);

  // --- Spawn an agent ---
  const [task, setTask] = useState("");
  const [skills, setSkills] = useState("");
  const [prefer, setPrefer] = useState("");
  const [spawnBusy, setSpawnBusy] = useState(false);
  const [spawnError, setSpawnError] = useState<string | null>(null);
  const [spawnResult, setSpawnResult] = useState<SpawnResult | null>(null);

  // --- Adapter source ---
  const [adapterId, setAdapterId] = useState("");
  const [srcBusy, setSrcBusy] = useState(false);
  const [srcError, setSrcError] = useState<string | null>(null);
  const [source, setSource] = useState<string | null>(null);

  const verbs = caps.data?.verbs ?? [];
  const adapterRecords = adapters.data?.adapters ?? [];

  function pickVerb(verbId: string) {
    const v = verbs.find((x) => x.id === verbId);
    if (v) {
      setNoun(v.noun);
      setVerb(v.id);
    }
  }

  async function invoke() {
    if (!noun.trim() || !verb.trim()) {
      setInvError("noun and verb are required.");
      return;
    }
    let p: Record<string, unknown>;
    let ctx: Record<string, unknown>;
    try {
      p = parseJson<Record<string, unknown>>(params, {});
    } catch (err) {
      setInvError(`params: ${errText(err)}`);
      return;
    }
    try {
      ctx = parseJson<Record<string, unknown>>(invContext, {});
    } catch (err) {
      setInvError(`context: ${errText(err)}`);
      return;
    }
    const rid = invRun.trim();
    if (rid) ctx = { ...ctx, run_id: rid };
    setInvBusy(true);
    setInvError(null);
    setInvResult(null);
    try {
      const req: InvokeRequest = { noun: noun.trim(), verb: verb.trim(), params: p };
      if (Object.keys(ctx).length > 0) req.context = ctx;
      const res = await api.invoke(req);
      setInvResult(res);
    } catch (err) {
      setInvError(errText(err));
    } finally {
      setInvBusy(false);
    }
  }

  async function spawn() {
    if (!task.trim()) {
      setSpawnError("task is required.");
      return;
    }
    let preferObj: Record<string, unknown>;
    try {
      preferObj = parseJson<Record<string, unknown>>(prefer, {});
    } catch (err) {
      setSpawnError(`prefer: ${errText(err)}`);
      return;
    }
    setSpawnBusy(true);
    setSpawnError(null);
    setSpawnResult(null);
    try {
      const req: SpawnRequest = { task: task.trim() };
      const sk = csvToList(skills);
      if (sk.length > 0) req.skills = sk;
      if (Object.keys(preferObj).length > 0) req.prefer = preferObj;
      // api.spawn is typed Promise<unknown> (free-form body); narrow to the
      // SpawnResult shape so effective_grants / run_id render.
      const res = (await api.spawn(req)) as SpawnResult;
      setSpawnResult(res);
    } catch (err) {
      setSpawnError(errText(err));
    } finally {
      setSpawnBusy(false);
    }
  }

  async function loadSource() {
    if (!adapterId.trim()) {
      setSrcError("pick an adapter.");
      return;
    }
    setSrcBusy(true);
    setSrcError(null);
    setSource(null);
    try {
      const res = await api.adapterSource(adapterId.trim());
      if (res.error) setSrcError(res.error);
      else setSource(res.source ?? "");
    } catch (err) {
      setSrcError(errText(err));
    } finally {
      setSrcBusy(false);
    }
  }

  return (
    <section className="panel">
      <div className="panel__head">
        <h2>Dev console</h2>
        <div className="panel__actions">
          <span className="muted">server-authoritative</span>
          <button
            className="btn"
            onClick={() => {
              caps.reload();
              adapters.reload();
            }}
          >
            Refresh
          </button>
        </div>
      </div>

      <p className="notice">
        Direct access to the kernel chokepoint. Every call is governed and
        scoped server-side: a denial, a human-in-the-loop pause or a degraded
        result is shown exactly as the kernel returned it. The tab gate is
        cosmetic.
      </p>

      <div className="form">
        <div className="form__title">Invoke a verb</div>
        <div className="form__actions">
          <label className="field field--wide">
            <span>pick from registry</span>
            <select value="" onChange={(e) => pickVerb(e.target.value)}>
              <option value="">
                {caps.loading ? "loading..." : "-- choose a verb --"}
              </option>
              {verbs.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.noun} / {v.id}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>noun</span>
            <input value={noun} onChange={(e) => setNoun(e.target.value)} />
          </label>
          <label className="field">
            <span>verb</span>
            <input value={verb} onChange={(e) => setVerb(e.target.value)} />
          </label>
          <label className="field">
            <span>run_id (optional)</span>
            <input value={invRun} onChange={(e) => setInvRun(e.target.value)} />
          </label>
        </div>
        <label className="field">
          <span>params (JSON)</span>
          <textarea
            className="code"
            value={params}
            onChange={(e) => setParams(e.target.value)}
          />
        </label>
        <label className="field">
          <span>context (JSON, optional)</span>
          <textarea
            className="code"
            value={invContext}
            onChange={(e) => setInvContext(e.target.value)}
          />
        </label>
        <div className="form__actions">
          <button
            className="btn btn--primary"
            disabled={invBusy}
            onClick={invoke}
          >
            {invBusy ? "..." : "Run"}
          </button>
          {invError && <span className="error">{invError}</span>}
        </div>
        {caps.error && (
          <p className="error">Failed to load capabilities: {caps.error}</p>
        )}
        {invResult && <InvokeResultView result={invResult} />}
      </div>

      <div className="form">
        <div className="form__title">Spawn an agent</div>
        <p className="muted">
          Runs an ephemeral agent under your grants. effective_grants in the
          result is the no-escalation evidence: the child can never exceed the
          initiator ceiling (SEC-29).
        </p>
        <label className="field">
          <span>task</span>
          <textarea
            className="code"
            value={task}
            onChange={(e) => setTask(e.target.value)}
          />
        </label>
        <div className="form__actions">
          <label className="field field--wide">
            <span>skills (comma-separated)</span>
            <input value={skills} onChange={(e) => setSkills(e.target.value)} />
          </label>
        </div>
        <label className="field">
          <span>prefer (JSON, optional)</span>
          <textarea
            className="code"
            value={prefer}
            onChange={(e) => setPrefer(e.target.value)}
          />
        </label>
        <div className="form__actions">
          <button
            className="btn btn--primary"
            disabled={spawnBusy}
            onClick={spawn}
          >
            {spawnBusy ? "..." : "Spawn"}
          </button>
          {spawnError && <span className="error">{spawnError}</span>}
        </div>
        {spawnResult && (
          <div className="stack">
            <div className="row-line">
              <span className="badge">{spawnResult.status ?? "?"}</span>
              {spawnResult.run_id && <RunLink runId={spawnResult.run_id} />}
            </div>
            {spawnResult.reason && (
              <p className="error">{spawnResult.reason}</p>
            )}
            <div className="row-line">
              <span className="muted">effective_grants (no escalation)</span>
              <GrantList grants={spawnResult.effective_grants} />
            </div>
            <CodeBlock value={spawnResult} />
          </div>
        )}
      </div>

      <div className="form">
        <div className="form__title">Adapter source</div>
        <p className="muted">
          The generated source for a registered adapter (read-only).
        </p>
        <div className="form__actions">
          <label className="field field--wide">
            <span>adapter</span>
            <select
              value={adapterId}
              onChange={(e) => setAdapterId(e.target.value)}
            >
              <option value="">
                {adapters.loading ? "loading..." : "-- choose an adapter --"}
              </option>
              {adapterRecords.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.id} ({a.runtime} {a.version})
                </option>
              ))}
            </select>
          </label>
          <button className="btn" disabled={srcBusy} onClick={loadSource}>
            {srcBusy ? "..." : "View source"}
          </button>
          {srcError && <span className="error">{srcError}</span>}
        </div>
        {adapters.error && (
          <p className="error">Failed to load adapters: {adapters.error}</p>
        )}
        {source !== null && <CodeBlock value={source} />}
      </div>
    </section>
  );
}
