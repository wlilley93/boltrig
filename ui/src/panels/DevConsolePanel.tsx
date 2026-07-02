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
import {
  CONSEQUENCE,
  EmptyState,
  Field,
  Hint,
  InfoCallout,
  PageIntro,
  Select,
  StatusBadge,
} from "./ux";
import { SchemaFormV2 } from "./uxForm";

// Safely parse the params JSON into an object for the schema form (an in-progress
// edit may be invalid; the form just sees {} until it is valid again).
function safeObj(text: string): Record<string, unknown> {
  try {
    const v = JSON.parse(text || "{}");
    return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

// Build a starter params object from a verb's JSON-Schema input_schema, so the
// box is never blank: each declared property gets a typed placeholder.
function skeletonFromSchema(schema: unknown): string {
  if (!schema || typeof schema !== "object") return "{}";
  const props = (schema as { properties?: Record<string, { type?: string }> }).properties;
  if (!props || typeof props !== "object") return "{}";
  const obj: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(props)) {
    const t = v?.type;
    obj[k] =
      t === "number" || t === "integer"
        ? 0
        : t === "boolean"
          ? false
          : t === "array"
            ? []
            : t === "object"
              ? {}
              : "";
  }
  return JSON.stringify(obj, null, 2);
}

function schemaKeys(schema: unknown): { required: string[]; optional: string[] } {
  const out = { required: [] as string[], optional: [] as string[] };
  if (!schema || typeof schema !== "object") return out;
  const s = schema as { properties?: Record<string, unknown>; required?: string[] };
  const req = new Set(s.required ?? []);
  for (const k of Object.keys(s.properties ?? {})) {
    (req.has(k) ? out.required : out.optional).push(k);
  }
  return out;
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

export function DevConsolePanel() {
  // The scoped verb registry powers the invoke picker; the adapter inventory
  // powers the source viewer; the skills list powers the spawn chips. All are
  // caller-scoped server-side.
  const caps = useFetch(() => api.capabilities(), []);
  const adapters = useFetch(() => api.adapters(), []);
  const skillsList = useFetch(() => api.skills(), []);

  // --- Invoke a verb ---
  const [noun, setNoun] = useState("");
  const [verb, setVerb] = useState("");
  const [params, setParams] = useState("{}");
  const [invRun, setInvRun] = useState("");
  const [invContext, setInvContext] = useState("");
  const [manual, setManual] = useState(false);
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
  const availableSkills = skillsList.data?.skills ?? [];
  const selectedVerb = verbs.find((v) => v.id === verb);
  const keys = schemaKeys(selectedVerb?.input_schema);

  function pickVerb(verbId: string) {
    const v = verbs.find((x) => x.id === verbId);
    if (v) {
      setNoun(v.noun);
      setVerb(v.id);
      // prefill the params box from the verb's schema unless the user has typed.
      if (params.trim() === "" || params.trim() === "{}") {
        setParams(skeletonFromSchema(v.input_schema));
      }
    }
  }

  function addSkill(id: string) {
    const have = csvToList(skills);
    if (!have.includes(id)) setSkills([...have, id].join(", "));
  }

  async function invoke() {
    if (!noun.trim() || !verb.trim()) {
      setInvError("Pick a verb first.");
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
      setSpawnError("Describe a task for the agent first.");
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
      setSrcError("Pick an adapter first.");
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

  const verbOptions = [
    { value: "", label: caps.loading ? "Loading verbs..." : "Choose a verb..." },
    ...verbs.map((v) => ({ value: v.id, label: `${v.noun} / ${v.id}` })),
  ];

  return (
    <section className="panel">
      <PageIntro
        title="Dev console"
        lead="Run one verb at a time, by hand, to test or debug a capability."
        how="Pick a verb from the registry; the kernel checks your grants and shows the real result - success, a denial, or a pause for human approval. Nothing here bypasses governance."
        actions={
          <button
            className="btn"
            onClick={() => {
              caps.reload();
              adapters.reload();
              skillsList.reload();
            }}
          >
            Refresh
          </button>
        }
      />

      <div className="form">
        <div className="form__title">Invoke a verb</div>

        {caps.error ? (
          <p className="error">Could not load the verb registry: {caps.error}</p>
        ) : verbs.length === 0 && !caps.loading ? (
          <EmptyState
            title="No verbs are available to you"
            body="Your grants decide which verbs appear here. Switch identity in the sidebar, or ask an admin to widen your scope."
          />
        ) : null}

        <Field
          label="Verb"
          hint="Choose an action from the capabilities you are allowed to call."
        >
          <Select value="" ariaLabel="Pick a verb" onChange={pickVerb} options={verbOptions} />
        </Field>

        {selectedVerb && (
          <div className="row-line" style={{ borderBottom: "none", paddingBottom: 0 }}>
            <span className="ux-hint">
              Selected: <code className="mono">{verb}</code> on{" "}
              <code className="mono">{noun}</code>
            </span>
            <StatusBadge value={selectedVerb.consequence} glossary={CONSEQUENCE} />
          </div>
        )}
        {selectedVerb?.consequence === "high" && (
          <InfoCallout tone="consequence" title="High-consequence verb">
            This performs a real, possibly irreversible action (it changes state,
            sends, or spends). It may pause for human approval before running.
          </InfoCallout>
        )}

        {selectedVerb && (keys.required.length || keys.optional.length) ? (
          <>
            <div className="form__title" style={{ fontSize: "var(--fs-sm)" }}>
              Arguments
            </div>
            <Hint>The values this verb expects. They are data the kernel passes in, never executed.</Hint>
            <SchemaFormV2
              schema={selectedVerb.input_schema}
              value={safeObj(params)}
              onChange={(o) => setParams(JSON.stringify(o, null, 2))}
            />
            <details>
              <summary className="ux-hint" style={{ cursor: "pointer" }}>
                Edit as JSON / show schema
              </summary>
              <textarea
                className="code"
                value={params}
                onChange={(e) => setParams(e.target.value)}
              />
              <CodeBlock value={selectedVerb.input_schema} />
            </details>
          </>
        ) : (
          <Field
            label="Arguments"
            hint={
              selectedVerb
                ? "This verb takes no arguments."
                : "Pick a verb to see the arguments it expects. Arguments are JSON the kernel passes to the verb - they are data, never executed."
            }
          >
            <textarea
              className="code"
              value={params}
              onChange={(e) => setParams(e.target.value)}
            />
          </Field>
        )}

        <details open={manual} onToggle={(e) => setManual((e.target as HTMLDetailsElement).open)}>
          <summary className="ux-hint" style={{ cursor: "pointer" }}>
            Advanced: run id, context, manual verb entry
          </summary>
          <div className="form__grid" style={{ marginTop: 10 }}>
            <Field
              label="Run id"
              hint="Attach this call to an existing run for audit threading. Leave blank to start fresh."
            >
              <input value={invRun} onChange={(e) => setInvRun(e.target.value)} />
            </Field>
            <Field label="Noun" hint="Set automatically from the verb you pick.">
              <input value={noun} onChange={(e) => setNoun(e.target.value)} />
            </Field>
            <Field label="Verb id" hint="Set automatically from the picker.">
              <input value={verb} onChange={(e) => setVerb(e.target.value)} />
            </Field>
          </div>
          <Field
            label="Extra context (JSON)"
            hint="Extra execution context for the kernel. Most calls leave this empty."
            example='{"idempotency_key": "..."}'
          >
            <textarea
              className="code"
              value={invContext}
              onChange={(e) => setInvContext(e.target.value)}
            />
          </Field>
        </details>

        <div className="form__actions">
          <button
            className="btn btn--primary"
            disabled={invBusy || !verb}
            onClick={invoke}
          >
            {invBusy ? "Running..." : "Run verb"}
          </button>
          {invError && <span className="error">{invError}</span>}
        </div>
        {invResult && <InvokeResultView result={invResult} />}
      </div>

      <div className="form">
        <div className="form__title">Spawn an agent</div>
        <InfoCallout title="Permissions the agent actually gets">
          A spawned agent runs under your grants and can never have more
          permissions than you do. The <code>effective_grants</code> in the
          result proves it stayed within your limits.
        </InfoCallout>
        <Field
          label="Task"
          hint="Describe what the agent should do, in plain language."
          example="triage the 5 oldest open tickets"
        >
          <textarea
            className="code"
            value={task}
            onChange={(e) => setTask(e.target.value)}
          />
        </Field>
        <Field
          label="Skills"
          hint="Which skills the agent may use (comma-separated). It still cannot exceed your grants."
        >
          <input value={skills} onChange={(e) => setSkills(e.target.value)} />
        </Field>
        {availableSkills.length > 0 && (
          <div className="kv">
            <span className="ux-hint">Add a skill:</span>
            {availableSkills.map((s) => (
              <button
                key={s.id}
                type="button"
                className="tag tag--accent"
                style={{ cursor: "pointer" }}
                title={`Add ${s.id}`}
                onClick={() => addSkill(s.id)}
              >
                {s.id}
              </button>
            ))}
          </div>
        )}
        <details>
          <summary className="ux-hint" style={{ cursor: "pointer" }}>
            Advanced: routing preferences
          </summary>
          <Field
            label="Prefer (JSON)"
            hint="Optional routing or runtime preferences for the agent. Leave empty for defaults."
            example='{"runtime": "pi-worker"}'
          >
            <textarea
              className="code"
              value={prefer}
              onChange={(e) => setPrefer(e.target.value)}
            />
          </Field>
        </details>
        <div className="form__actions">
          <button
            className="btn btn--primary"
            disabled={spawnBusy}
            onClick={spawn}
          >
            {spawnBusy ? "Spawning..." : "Spawn agent"}
          </button>
          {spawnError && <span className="error">{spawnError}</span>}
        </div>
        {spawnResult ? (
          <div className="stack">
            <div className="row-line">
              <span className="badge">{spawnResult.status ?? "?"}</span>
              {spawnResult.run_id && <RunLink runId={spawnResult.run_id} />}
            </div>
            {spawnResult.reason && <p className="error">{spawnResult.reason}</p>}
            <div className="row-line">
              <span className="muted">Permissions the agent got</span>
              <GrantList grants={spawnResult.effective_grants} />
            </div>
            <CodeBlock value={spawnResult} />
          </div>
        ) : (
          <Hint>Run a spawn to see the agent's permissions and result here.</Hint>
        )}
      </div>

      <div className="form">
        <div className="form__title">Adapter source</div>
        <p className="ux-hint">
          The generated source for a registered adapter, read-only - useful to
          see exactly what a verb runs.
        </p>
        <div className="form__actions">
          <Field label="Adapter">
            <Select
              value={adapterId}
              ariaLabel="Pick an adapter"
              onChange={setAdapterId}
              options={[
                { value: "", label: adapters.loading ? "Loading adapters..." : "Choose an adapter..." },
                ...adapterRecords.map((a) => ({
                  value: a.id,
                  label: `${a.id} (${a.runtime} ${a.version})`,
                })),
              ]}
            />
          </Field>
          <button className="btn" disabled={srcBusy} onClick={loadSource}>
            {srcBusy ? "Loading..." : "View source"}
          </button>
          {srcError && <span className="error">{srcError}</span>}
        </div>
        {adapters.error && (
          <p className="error">Could not load adapters: {adapters.error}</p>
        )}
        {source !== null && <CodeBlock value={source} />}
      </div>
    </section>
  );
}
