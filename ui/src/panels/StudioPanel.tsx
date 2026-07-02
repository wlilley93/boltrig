// Round Three authoring hub. Four sub-studios behind internal sub-tabs (no
// router): Skills, Router authoring, Adapter Studio and Workflow Studio.
// Authoring requires a permitting role; the server is the real gate (403), but
// the panel also shows a notice for non-author identities so the surface is
// honest. Generated adapters / MCP servers land inert (activated: false) and a
// reviewer must activate them (SEC-22). test-spawn returns effective_grants so
// an author can see the child never escalates past their own grants (SEC-29).

import { useState } from "react";

import { api } from "../api/client";
import type {
  AdapterRecord,
  GenerateAdapterResponse,
  SkillSummary,
  SpawnResult,
  StatusAck,
  TargetTypeValue,
  VerbInfo,
  WorkflowRunDescriptor,
  WorkflowRunRecord,
  WorkflowSourceValue,
  WorkflowSummary,
} from "../api/types";
import { useIdentity } from "../identity";
import { useFetch } from "../useFetch";
import {
  CodeBlock,
  GrantList,
  RunLink,
  csvToList,
  errText,
  listToCsv,
  parseJson,
  runBadgeClass,
  stepBadgeClass,
} from "./shared";
import { WorkflowCanvas } from "./WorkflowCanvas";
import { Field, Hint, PageIntro, Select } from "./ux";
import { SegmentedV2 } from "./uxForm";

const AUTHOR_ROLES: ReadonlySet<string> = new Set([
  "org-admin",
  "department-head",
  "manager",
  "lead",
  "integrator",
]);

type StudioTab = "skills" | "router" | "adapters" | "workflows";

const STUDIO_TABS: ReadonlyArray<{ id: StudioTab; label: string }> = [
  { id: "skills", label: "Skills" },
  { id: "router", label: "Router authoring" },
  { id: "adapters", label: "Adapter Studio" },
  { id: "workflows", label: "Workflow Studio" },
];

// Shared rendering of a {status, reason} acknowledgement.
function AckLine({ ack }: { ack: StatusAck | null }) {
  if (!ack) return null;
  if (ack.status === "ok") {
    const parts = [ack.id, ack.version ? `v${ack.version}` : null].filter(
      Boolean,
    );
    return <p className="ok">Saved {parts.join(" ") || "ok"}.</p>;
  }
  return (
    <p className="error">
      {ack.status}: {ack.reason ?? "request rejected"}
    </p>
  );
}

// --- Skill Studio -----------------------------------------------------------

function SkillsStudio() {
  const skills = useFetch(() => api.skills(), []);
  const caps = useFetch(() => api.capabilities(), []);

  const [id, setId] = useState("");
  const [version, setVersion] = useState("1.0.0");
  const [fragment, setFragment] = useState("");
  const [grants, setGrants] = useState("");
  const [ctxReq, setCtxReq] = useState("{}");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ack, setAck] = useState<StatusAck | null>(null);

  const [spawnSkill, setSpawnSkill] = useState("");
  const [spawnTask, setSpawnTask] = useState("");
  const [spawnBusy, setSpawnBusy] = useState(false);
  const [spawnError, setSpawnError] = useState<string | null>(null);
  const [spawnResult, setSpawnResult] = useState<SpawnResult | null>(null);

  async function upsert() {
    if (!id.trim()) {
      setError("Skill id is required.");
      return;
    }
    let contextRequirements: Record<string, unknown>;
    try {
      contextRequirements = parseJson<Record<string, unknown>>(ctxReq, {});
    } catch (err) {
      setError(`context_requirements: ${errText(err)}`);
      return;
    }
    setBusy(true);
    setError(null);
    setAck(null);
    try {
      const res = await api.upsertSkill({
        id: id.trim(),
        version: version.trim() || "1.0.0",
        prompt_fragment: fragment,
        tool_grants: csvToList(grants),
        context_requirements: contextRequirements,
      });
      setAck(res);
      if (res.status === "ok") skills.reload();
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  async function testSpawn() {
    const sid = spawnSkill.trim();
    if (!sid) {
      setSpawnError("Skill id is required.");
      return;
    }
    setSpawnBusy(true);
    setSpawnError(null);
    setSpawnResult(null);
    try {
      const res = await api.testSpawn(sid, {
        task: spawnTask.trim() || `test ${sid}`,
      });
      setSpawnResult(res);
    } catch (err) {
      setSpawnError(errText(err));
    } finally {
      setSpawnBusy(false);
    }
  }

  const list: SkillSummary[] = skills.data?.skills ?? [];
  const allVerbs = caps.data?.verbs ?? [];
  function addGrant(id: string) {
    const have = csvToList(grants);
    if (!have.includes(id)) setGrants([...have, id].join(", "));
  }

  return (
    <div className="cols">
      <div className="stack">
        <div className="form">
          <div className="form__title">Create or update a skill</div>
          <Hint>A skill gives an agent an instruction plus the permissions it needs.</Hint>
          <div className="form__grid">
            <Field label="Skill id" hint="Lowercase, dotted, unique." example="triage.summarise">
              <input value={id} onChange={(e) => setId(e.target.value)} />
            </Field>
            <Field label="Version" hint="Semver; bump on every change.">
              <input value={version} onChange={(e) => setVersion(e.target.value)} />
            </Field>
          </div>
          <Field
            label="Instruction"
            hint="The text injected into the agent when this skill loads."
            example="Summarise the ticket in 3 bullets"
          >
            <textarea
              className="code"
              value={fragment}
              onChange={(e) => setFragment(e.target.value)}
            />
          </Field>
          <Field
            label="Permissions"
            hint="The verbs an agent using this skill may call (comma-separated). It still can't exceed the caller's own grants."
          >
            <input
              value={grants}
              placeholder="ticket.read, ticket.comment"
              onChange={(e) => setGrants(e.target.value)}
            />
          </Field>
          {allVerbs.length > 0 && (
            <div className="kv">
              <span className="ux-hint">Add a permission:</span>
              {allVerbs.map((v) => (
                <button
                  key={v.id}
                  type="button"
                  className="tag tag--accent"
                  style={{ cursor: "pointer" }}
                  onClick={() => addGrant(v.id)}
                >
                  {v.id}
                </button>
              ))}
            </div>
          )}
          <details>
            <summary className="ux-hint" style={{ cursor: "pointer" }}>
              Advanced: context requirements (JSON)
            </summary>
            <Field
              label="Context requirements (JSON)"
              hint="Fields the skill needs in context before it can run."
              example='{"requires": ["customer_id"]}'
            >
              <textarea
                className="code"
                value={ctxReq}
                onChange={(e) => setCtxReq(e.target.value)}
              />
            </Field>
          </details>
          <div className="form__actions">
            <button className="btn btn--primary" disabled={busy} onClick={upsert}>
              {busy ? "..." : "Save skill"}
            </button>
            <AckLine ack={ack} />
            {error && <span className="error">{error}</span>}
          </div>
        </div>

        <div className="form">
          <div className="form__title">Test spawn</div>
          <p className="muted">
            Runs the skill under your grants (a ceiling). The returned
            effective_grants prove the child cannot escalate past you.
          </p>
          <div className="form__grid">
            <label className="field">
              <span>skill id</span>
              <input
                value={spawnSkill}
                onChange={(e) => setSpawnSkill(e.target.value)}
              />
            </label>
            <label className="field">
              <span>task</span>
              <input
                value={spawnTask}
                onChange={(e) => setSpawnTask(e.target.value)}
              />
            </label>
          </div>
          <div className="form__actions">
            <button className="btn" disabled={spawnBusy} onClick={testSpawn}>
              {spawnBusy ? "..." : "Test spawn"}
            </button>
            {spawnError && <span className="error">{spawnError}</span>}
          </div>
          {spawnResult &&
            (spawnResult.status === "denied" ? (
              <p className="error">
                denied: {spawnResult.reason ?? "not permitted"}
              </p>
            ) : (
              <div className="stack">
                <div className="row-line">
                  <span className="muted">effective_grants</span>
                  <GrantList grants={spawnResult.effective_grants} />
                </div>
                <CodeBlock value={spawnResult} />
              </div>
            ))}
        </div>
      </div>

      <div className="list-card">
        <div className="list-card__head">
          <h3>Skills</h3>
          <div className="panel__actions">
            <span className="muted">{list.length}</span>
            <button className="btn" onClick={() => skills.reload()}>
              Refresh
            </button>
          </div>
        </div>
        <div className="list-card__body">
          {skills.loading && !skills.data && (
            <p className="muted">Loading...</p>
          )}
          {skills.error && (
            <p className="error">Failed to load: {skills.error}</p>
          )}
          {!skills.loading && list.length === 0 && (
            <p className="muted">No skills yet.</p>
          )}
          {list.map((s) => (
            <div className="row-line" key={`${s.id}@${s.version}`}>
              <div>
                <code>{s.id}</code> <span className="muted">v{s.version}</span>
              </div>
              <GrantList grants={s.tool_grants} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// --- Router authoring -------------------------------------------------------

function NounForm() {
  const [id, setId] = useState("");
  const [description, setDescription] = useState("");
  const [schema, setSchema] = useState("{}");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ack, setAck] = useState<StatusAck | null>(null);

  async function submit() {
    if (!id.trim()) {
      setError("Noun id is required.");
      return;
    }
    let parsed: Record<string, unknown>;
    try {
      parsed = parseJson<Record<string, unknown>>(schema, {});
    } catch (err) {
      setError(`schema: ${errText(err)}`);
      return;
    }
    setBusy(true);
    setError(null);
    setAck(null);
    try {
      setAck(
        await api.upsertNoun({
          id: id.trim(),
          description,
          schema: parsed,
        }),
      );
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="form">
      <div className="form__title">Add noun</div>
      <div className="form__grid">
        <label className="field">
          <span>id</span>
          <input value={id} onChange={(e) => setId(e.target.value)} />
        </label>
        <label className="field">
          <span>description</span>
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>
      </div>
      <label className="field">
        <span>schema (JSON)</span>
        <textarea
          className="code"
          value={schema}
          onChange={(e) => setSchema(e.target.value)}
        />
      </label>
      <div className="form__actions">
        <button className="btn btn--primary" disabled={busy} onClick={submit}>
          {busy ? "..." : "Save noun"}
        </button>
        <AckLine ack={ack} />
        {error && <span className="error">{error}</span>}
      </div>
    </div>
  );
}

function VerbForm() {
  const [id, setId] = useState("");
  const [nounId, setNounId] = useState("");
  const [inputSchema, setInputSchema] = useState("{}");
  const [outputSchema, setOutputSchema] = useState("{}");
  const [consequence, setConsequence] = useState<"low" | "high">("low");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ack, setAck] = useState<StatusAck | null>(null);

  async function submit() {
    if (!id.trim() || !nounId.trim()) {
      setError("Verb id and noun_id are required.");
      return;
    }
    let inSchema: Record<string, unknown>;
    let outSchema: Record<string, unknown>;
    try {
      inSchema = parseJson<Record<string, unknown>>(inputSchema, {});
      outSchema = parseJson<Record<string, unknown>>(outputSchema, {});
    } catch (err) {
      setError(`schema: ${errText(err)}`);
      return;
    }
    setBusy(true);
    setError(null);
    setAck(null);
    try {
      setAck(
        await api.upsertVerb({
          id: id.trim(),
          noun_id: nounId.trim(),
          input_schema: inSchema,
          output_schema: outSchema,
          consequence,
        }),
      );
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="form">
      <div className="form__title">Add verb</div>
      <div className="form__grid">
        <label className="field">
          <span>id</span>
          <input value={id} onChange={(e) => setId(e.target.value)} />
        </label>
        <label className="field">
          <span>noun_id</span>
          <input value={nounId} onChange={(e) => setNounId(e.target.value)} />
        </label>
        <label className="field">
          <span>consequence</span>
          <select
            value={consequence}
            onChange={(e) =>
              setConsequence(e.target.value === "high" ? "high" : "low")
            }
          >
            <option value="low">low</option>
            <option value="high">high</option>
          </select>
        </label>
      </div>
      <label className="field">
        <span>input_schema (JSON)</span>
        <textarea
          className="code"
          value={inputSchema}
          onChange={(e) => setInputSchema(e.target.value)}
        />
      </label>
      <label className="field">
        <span>output_schema (JSON)</span>
        <textarea
          className="code"
          value={outputSchema}
          onChange={(e) => setOutputSchema(e.target.value)}
        />
      </label>
      <div className="form__actions">
        <button className="btn btn--primary" disabled={busy} onClick={submit}>
          {busy ? "..." : "Save verb"}
        </button>
        <AckLine ack={ack} />
        {error && <span className="error">{error}</span>}
      </div>
    </div>
  );
}

function BindingForm() {
  const caps = useFetch(() => api.capabilities(), []);
  const adapters = useFetch(() => api.adapters(), []);
  const [verbId, setVerbId] = useState("");
  const [targetType, setTargetType] = useState<TargetTypeValue>("adapter");
  const [targetRef, setTargetRef] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ack, setAck] = useState<StatusAck | null>(null);

  async function submit() {
    if (!verbId.trim() || !targetRef.trim()) {
      setError("Pick a verb and what should run it.");
      return;
    }
    setBusy(true);
    setError(null);
    setAck(null);
    try {
      setAck(
        await api.setBinding(verbId.trim(), {
          target_type: targetType,
          target_ref: targetRef.trim(),
        }),
      );
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  const verbOptions = [
    { value: "", label: "Choose a verb..." },
    ...(caps.data?.verbs ?? []).map((v) => ({ value: v.id, label: v.id })),
  ];
  const adapterOptions = [
    { value: "", label: "Choose an adapter..." },
    ...(adapters.data?.adapters ?? []).map((a) => ({ value: a.id, label: a.id })),
  ];

  return (
    <div className="form">
      <div className="form__title">Set binding</div>
      <Hint>Wire a verb to what actually runs it - an adapter, or an agent.</Hint>
      <div className="form__grid">
        <Field label="Verb" hint="The action to wire up.">
          <Select value={verbId} ariaLabel="Verb" onChange={setVerbId} options={verbOptions} />
        </Field>
        <Field label="Runs via" hint="An adapter (a service) or an agent (a reasoning model).">
          <SegmentedV2
            value={targetType}
            ariaLabel="Target type"
            onChange={(v) => {
              setTargetType(v === "agent" ? "agent" : "adapter");
              setTargetRef("");
            }}
            options={[
              { value: "adapter", label: "An adapter" },
              { value: "agent", label: "An agent" },
            ]}
          />
        </Field>
        <Field
          label={targetType === "adapter" ? "Which adapter" : "Which agent"}
          hint={
            targetType === "adapter"
              ? "The registered adapter that fulfils this verb."
              : "The agent id that fulfils this verb."
          }
        >
          {targetType === "adapter" ? (
            <Select value={targetRef} ariaLabel="Adapter" onChange={setTargetRef} options={adapterOptions} />
          ) : (
            <input value={targetRef} onChange={(e) => setTargetRef(e.target.value)} />
          )}
        </Field>
      </div>
      <div className="form__actions">
        <button className="btn btn--primary" disabled={busy} onClick={submit}>
          {busy ? "Saving..." : "Set binding"}
        </button>
        <AckLine ack={ack} />
        {error && <span className="error">{error}</span>}
      </div>
    </div>
  );
}

function RouterStudio() {
  return (
    <div className="cols">
      <NounForm />
      <VerbForm />
      <BindingForm />
    </div>
  );
}

// --- Adapter Studio ---------------------------------------------------------

function AdapterStudio() {
  const inventory = useFetch(() => api.adapters(), []);

  const [adapterId, setAdapterId] = useState("");
  const [spec, setSpec] = useState("{}");
  const [genBusy, setGenBusy] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  const [gen, setGen] = useState<GenerateAdapterResponse | null>(null);

  const [actId, setActId] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [actBusy, setActBusy] = useState(false);
  const [actError, setActError] = useState<string | null>(null);
  const [actResult, setActResult] = useState<string[] | null>(null);

  const [mcpId, setMcpId] = useState("");
  const [mcpUrl, setMcpUrl] = useState("");
  const [mcpToken, setMcpToken] = useState("");
  const [mcpBusy, setMcpBusy] = useState(false);
  const [mcpError, setMcpError] = useState<string | null>(null);
  const [mcpAck, setMcpAck] = useState<StatusAck | null>(null);

  async function generate() {
    if (!adapterId.trim()) {
      setGenError("adapter_id is required.");
      return;
    }
    let parsedSpec: unknown;
    try {
      parsedSpec = parseJson<unknown>(spec, {});
    } catch (err) {
      setGenError(`spec: ${errText(err)}`);
      return;
    }
    setGenBusy(true);
    setGenError(null);
    setGen(null);
    try {
      const res = await api.generateAdapter({
        adapter_id: adapterId.trim(),
        spec: parsedSpec,
      });
      setGen(res);
      if (res.status === "ok") inventory.reload();
    } catch (err) {
      setGenError(errText(err));
    } finally {
      setGenBusy(false);
    }
  }

  async function activate() {
    if (!actId.trim()) {
      setActError("adapter id is required.");
      return;
    }
    setActBusy(true);
    setActError(null);
    setActResult(null);
    try {
      const res = await api.activateAdapter(actId.trim(), {
        reviewer: reviewer.trim() || undefined,
      });
      if (res.error || res.reason) {
        setActError(res.error ?? res.reason ?? "activation failed");
      } else {
        setActResult(res.verbs ?? []);
        inventory.reload();
      }
    } catch (err) {
      setActError(errText(err));
    } finally {
      setActBusy(false);
    }
  }

  async function registerMcp() {
    if (!mcpId.trim()) {
      setMcpError("MCP server id is required.");
      return;
    }
    setMcpBusy(true);
    setMcpError(null);
    setMcpAck(null);
    try {
      const res = await api.registerMcpServer({
        id: mcpId.trim(),
        url: mcpUrl.trim() || undefined,
        token: mcpToken.trim() || undefined,
      });
      setMcpAck(res);
      if (res.status === "ok") inventory.reload();
    } catch (err) {
      setMcpError(errText(err));
    } finally {
      setMcpBusy(false);
    }
  }

  const records: AdapterRecord[] = inventory.data?.adapters ?? [];

  return (
    <div className="cols">
      <div className="stack">
        <div className="form">
          <div className="form__title">Generate adapter from OpenAPI</div>
          <p className="muted">
            Generated adapters load inert (activated: false): a reviewer must
            activate before any verb is bound (SEC-22).
          </p>
          <label className="field">
            <span>adapter_id</span>
            <input
              value={adapterId}
              onChange={(e) => setAdapterId(e.target.value)}
            />
          </label>
          <label className="field">
            <span>spec (OpenAPI JSON)</span>
            <textarea
              className="code"
              value={spec}
              onChange={(e) => setSpec(e.target.value)}
            />
          </label>
          <div className="form__actions">
            <button
              className="btn btn--primary"
              disabled={genBusy}
              onClick={generate}
            >
              {genBusy ? "..." : "Generate"}
            </button>
            {genError && <span className="error">{genError}</span>}
          </div>
          {gen &&
            (gen.status === "ok" ? (
              <div className="stack">
                <div className="row-line">
                  <span>
                    <code>{gen.id}</code>{" "}
                    <span
                      className={`badge ${gen.activated ? "badge--activated" : "badge--inert"}`}
                    >
                      {gen.activated ? "activated" : "inert"}
                    </span>
                  </span>
                  <span className="muted">{gen.verbs?.length ?? 0} verb(s)</span>
                </div>
                <CodeBlock value={gen.verbs ?? []} />
              </div>
            ) : (
              <p className="error">
                {gen.status}: {gen.reason ?? "rejected"}
              </p>
            ))}
        </div>

        <div className="form">
          <div className="form__title">Activate adapter</div>
          <div className="form__grid">
            <label className="field">
              <span>adapter id</span>
              <input
                value={actId}
                onChange={(e) => setActId(e.target.value)}
              />
            </label>
            <label className="field">
              <span>reviewer</span>
              <input
                value={reviewer}
                onChange={(e) => setReviewer(e.target.value)}
              />
            </label>
          </div>
          <div className="form__actions">
            <button className="btn" disabled={actBusy} onClick={activate}>
              {actBusy ? "..." : "Activate"}
            </button>
            {actError && <span className="error">{actError}</span>}
          </div>
          {actResult && (
            <p className="ok">
              Activated. Bound verbs: {actResult.join(", ") || "(none)"}
            </p>
          )}
        </div>

        <div className="form">
          <div className="form__title">Register MCP server</div>
          <div className="form__grid">
            <label className="field">
              <span>id</span>
              <input value={mcpId} onChange={(e) => setMcpId(e.target.value)} />
            </label>
            <label className="field">
              <span>url</span>
              <input
                value={mcpUrl}
                onChange={(e) => setMcpUrl(e.target.value)}
              />
            </label>
            <label className="field">
              <span>token</span>
              <input
                value={mcpToken}
                onChange={(e) => setMcpToken(e.target.value)}
              />
            </label>
          </div>
          <div className="form__actions">
            <button className="btn" disabled={mcpBusy} onClick={registerMcp}>
              {mcpBusy ? "..." : "Register"}
            </button>
            <AckLine ack={mcpAck} />
            {mcpError && <span className="error">{mcpError}</span>}
          </div>
        </div>
      </div>

      <div className="list-card">
        <div className="list-card__head">
          <h3>Adapter inventory</h3>
          <button className="btn" onClick={() => inventory.reload()}>
            Refresh
          </button>
        </div>
        <div className="list-card__body">
          {inventory.loading && !inventory.data && (
            <p className="muted">Loading...</p>
          )}
          {inventory.error && (
            <p className="error">Failed to load: {inventory.error}</p>
          )}
          {!inventory.loading && records.length === 0 && (
            <p className="muted">No adapters registered.</p>
          )}
          {records.map((a) => (
            <div className="row-line" key={a.id}>
              <div>
                <code>{a.id}</code>{" "}
                <span className="muted">
                  {a.runtime} v{a.version}
                </span>
              </div>
              <div className="kv">
                <span
                  className={`badge ${a.activated ? "badge--activated" : "badge--inert"}`}
                >
                  {a.activated ? "activated" : "inert"}
                </span>
                <span className={`badge badge--${a.health}`}>{a.health}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// --- Workflow Studio --------------------------------------------------------

// View toggle inside the Workflow Studio: the existing form flow or the new
// React Flow canvas. Both round-trip the same definition.steps shape.
type WorkflowView = "form" | "canvas";

const TZ_OPTIONS = [
  "UTC",
  "Europe/London",
  "Europe/Paris",
  "America/New_York",
  "America/Chicago",
  "America/Los_Angeles",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Sydney",
].map((z) => ({ value: z, label: z }));

const CRON_PRESETS: ReadonlyArray<{ label: string; value: string }> = [
  { label: "Hourly", value: "0 * * * *" },
  { label: "Daily 9am", value: "0 9 * * *" },
  { label: "Weekdays 9am", value: "0 9 * * 1-5" },
  { label: "Mondays 9am", value: "0 9 * * 1" },
];

function WorkflowForm() {
  const workflows = useFetch(() => api.workflows(), []);

  const [id, setId] = useState("");
  const [version, setVersion] = useState("1.0.0");
  const [source, setSource] = useState<WorkflowSourceValue>("precreated");
  const [definition, setDefinition] = useState("{}");
  const [tags, setTags] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ack, setAck] = useState<StatusAck | null>(null);

  const [schedId, setSchedId] = useState("");
  const [cron, setCron] = useState("");
  const [tz, setTz] = useState("UTC");
  const [schedBusy, setSchedBusy] = useState(false);
  const [schedError, setSchedError] = useState<string | null>(null);
  const [schedResult, setSchedResult] = useState<unknown>(null);

  const [trigId, setTrigId] = useState("");
  const [inputs, setInputs] = useState("{}");
  const [trigBusy, setTrigBusy] = useState(false);
  const [trigError, setTrigError] = useState<string | null>(null);
  const [trigResult, setTrigResult] = useState<WorkflowRunDescriptor | null>(
    null,
  );

  const [execId, setExecId] = useState("");
  const [execInputs, setExecInputs] = useState("{}");
  const [execBusy, setExecBusy] = useState(false);
  const [execError, setExecError] = useState<string | null>(null);
  const [execResult, setExecResult] = useState<WorkflowRunRecord | null>(null);

  const [runsId, setRunsId] = useState("");
  const [runsBusy, setRunsBusy] = useState(false);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [runs, setRuns] = useState<string[] | null>(null);

  // The scoped verb registry powers the palette: each id can be pasted as a
  // step "action" in the definition JSON above.
  const caps = useFetch(() => api.capabilities(), []);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  async function upsert() {
    if (!id.trim()) {
      setError("Workflow id is required.");
      return;
    }
    let def: Record<string, unknown>;
    try {
      def = parseJson<Record<string, unknown>>(definition, {});
    } catch (err) {
      setError(`definition: ${errText(err)}`);
      return;
    }
    setBusy(true);
    setError(null);
    setAck(null);
    try {
      const res = await api.upsertWorkflow({
        id: id.trim(),
        version: version.trim() || "1.0.0",
        source,
        definition: def,
        intent_tags: csvToList(tags),
      });
      setAck(res);
      if (res.status === "ok") workflows.reload();
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  async function schedule() {
    if (!schedId.trim() || !cron.trim()) {
      setSchedError("workflow id and cron are required.");
      return;
    }
    setSchedBusy(true);
    setSchedError(null);
    setSchedResult(null);
    try {
      const res = await api.scheduleWorkflow(schedId.trim(), {
        cron: cron.trim(),
        timezone: tz.trim() || "UTC",
      });
      if (res.status === "ok") setSchedResult(res.schedule);
      else setSchedError(res.reason ?? "schedule rejected");
    } catch (err) {
      setSchedError(errText(err));
    } finally {
      setSchedBusy(false);
    }
  }

  async function trigger() {
    if (!trigId.trim()) {
      setTrigError("workflow id is required.");
      return;
    }
    let parsedInputs: Record<string, unknown>;
    try {
      parsedInputs = parseJson<Record<string, unknown>>(inputs, {});
    } catch (err) {
      setTrigError(`inputs: ${errText(err)}`);
      return;
    }
    setTrigBusy(true);
    setTrigError(null);
    setTrigResult(null);
    try {
      const res = await api.triggerWorkflow(trigId.trim(), {
        inputs: parsedInputs,
      });
      if (res.error) setTrigError(res.error);
      else setTrigResult(res);
    } catch (err) {
      setTrigError(errText(err));
    } finally {
      setTrigBusy(false);
    }
  }

  async function loadRuns() {
    if (!runsId.trim()) {
      setRunsError("workflow id is required.");
      return;
    }
    setRunsBusy(true);
    setRunsError(null);
    setRuns(null);
    try {
      const res = await api.workflowRuns(runsId.trim());
      setRuns(res.runs);
    } catch (err) {
      setRunsError(errText(err));
    } finally {
      setRunsBusy(false);
    }
  }

  async function execute() {
    if (!execId.trim()) {
      setExecError("workflow id is required.");
      return;
    }
    let parsedInputs: Record<string, unknown>;
    try {
      parsedInputs = parseJson<Record<string, unknown>>(execInputs, {});
    } catch (err) {
      setExecError(`inputs: ${errText(err)}`);
      return;
    }
    setExecBusy(true);
    setExecError(null);
    setExecResult(null);
    try {
      const res = await api.executeWorkflow(execId.trim(), parsedInputs);
      setExecResult(res);
    } catch (err) {
      setExecError(errText(err));
    } finally {
      setExecBusy(false);
    }
  }

  async function copyVerb(verbId: string) {
    try {
      await navigator.clipboard.writeText(verbId);
      setCopiedId(verbId);
    } catch {
      // Clipboard may be unavailable (insecure context); fail quietly.
    }
  }

  const list: WorkflowSummary[] = workflows.data?.workflows ?? [];
  const wfOptions = [
    { value: "", label: "Choose a workflow..." },
    ...list.map((w) => ({ value: w.id, label: w.id })),
  ];
  const verbs: VerbInfo[] = caps.data?.verbs ?? [];

  return (
    <div className="cols">
      <div className="stack">
        <div className="form">
          <div className="form__title">Upsert workflow</div>
          <div className="form__grid">
            <label className="field">
              <span>id</span>
              <input value={id} onChange={(e) => setId(e.target.value)} />
            </label>
            <label className="field">
              <span>version</span>
              <input
                value={version}
                onChange={(e) => setVersion(e.target.value)}
              />
            </label>
            <label className="field">
              <span>source</span>
              <select
                value={source}
                onChange={(e) =>
                  setSource(e.target.value as WorkflowSourceValue)
                }
              >
                <option value="precreated">precreated</option>
                <option value="generated">generated</option>
                <option value="learned">learned</option>
              </select>
            </label>
          </div>
          <label className="field">
            <span>definition / steps (JSON)</span>
            <textarea
              className="code"
              value={definition}
              onChange={(e) => setDefinition(e.target.value)}
            />
          </label>
          <label className="field">
            <span>intent_tags (comma list)</span>
            <input value={tags} onChange={(e) => setTags(e.target.value)} />
          </label>
          <div className="form__actions">
            <button
              className="btn btn--primary"
              disabled={busy}
              onClick={upsert}
            >
              {busy ? "..." : "Save workflow"}
            </button>
            <AckLine ack={ack} />
            {error && <span className="error">{error}</span>}
          </div>
        </div>

        <div className="form">
          <div className="form__title">Schedule (cron)</div>
          <div className="form__grid">
            <Field label="Workflow" hint="The workflow to run on a schedule.">
              <Select value={schedId} ariaLabel="Workflow" onChange={setSchedId} options={wfOptions} />
            </Field>
            <Field label="When (cron)" hint="A 5-field cron expression, or pick a preset below." example="0 9 * * 1">
              <input value={cron} placeholder="0 9 * * 1" onChange={(e) => setCron(e.target.value)} />
            </Field>
            <Field label="Timezone" hint="The timezone the schedule runs in.">
              <Select value={tz} ariaLabel="Timezone" onChange={setTz} options={TZ_OPTIONS} />
            </Field>
          </div>
          <div className="kv">
            <span className="ux-hint">Presets:</span>
            {CRON_PRESETS.map((p) => (
              <button
                key={p.value}
                type="button"
                className="tag tag--accent"
                style={{ cursor: "pointer" }}
                title={p.value}
                onClick={() => setCron(p.value)}
              >
                {p.label}
              </button>
            ))}
          </div>
          <div className="form__actions">
            <button className="btn" disabled={schedBusy} onClick={schedule}>
              {schedBusy ? "..." : "Schedule"}
            </button>
            {schedError && <span className="error">{schedError}</span>}
          </div>
          {schedResult !== null && <CodeBlock value={schedResult} />}
        </div>

        <div className="form">
          <div className="form__title">Trigger</div>
          <Field label="Workflow" hint="The workflow to start now.">
            <Select value={trigId} ariaLabel="Workflow" onChange={setTrigId} options={wfOptions} />
          </Field>
          <Field label="Inputs (JSON)" hint="Values passed into the workflow." example='{"ticket_id": "4821"}'>
            <textarea
              className="code"
              value={inputs}
              onChange={(e) => setInputs(e.target.value)}
            />
          </Field>
          <div className="form__actions">
            <button className="btn" disabled={trigBusy} onClick={trigger}>
              {trigBusy ? "..." : "Trigger"}
            </button>
            {trigError && <span className="error">{trigError}</span>}
          </div>
          {trigResult && (
            <div className="stack">
              <div className="kv">
                <span className="badge">engine: {trigResult.engine}</span>
                <span
                  className={`badge ${trigResult.durable ? "badge--activated" : "badge--inert"}`}
                >
                  {trigResult.durable ? "durable" : "in-process"}
                </span>
                {trigResult.status && (
                  <span className="badge">{trigResult.status}</span>
                )}
                {trigResult.run_id && <RunLink runId={trigResult.run_id} />}
              </div>
              <CodeBlock value={trigResult} />
            </div>
          )}
        </div>

        <div className="form">
          <div className="form__title">Execute (run steps)</div>
          <Field label="Workflow" hint="The workflow to run step-by-step now.">
            <Select value={execId} ariaLabel="Workflow" onChange={setExecId} options={wfOptions} />
          </Field>
          <Field label="Inputs (JSON)" hint="Values passed into the workflow." example='{"ticket_id": "4821"}'>
            <textarea
              className="code"
              value={execInputs}
              onChange={(e) => setExecInputs(e.target.value)}
            />
          </Field>
          <div className="form__actions">
            <button
              className="btn btn--primary"
              disabled={execBusy}
              onClick={execute}
            >
              {execBusy ? "..." : "Execute"}
            </button>
            {execError && <span className="error">{execError}</span>}
          </div>
          {execResult && (
            <div className="stack">
              <div className="kv">
                <span className={`badge ${runBadgeClass(execResult.status)}`}>
                  {execResult.status}
                </span>
                <RunLink runId={execResult.run_id} />
                <span className="muted">
                  {execResult.workflow_id} v{execResult.version}
                </span>
              </div>
              {execResult.steps.length === 0 ? (
                <p className="muted">No steps.</p>
              ) : (
                <ul className="verb-list">
                  {execResult.steps.map((s, i) => (
                    <li className="verb-row" key={`${s.id}-${i}`}>
                      <div className="verb-row__main">
                        <code className="verb-row__id">{s.id}</code>
                        {s.action && (
                          <span className="muted">{s.action}</span>
                        )}
                        <span className={`badge ${stepBadgeClass(s.status)}`}>
                          {s.status}
                        </span>
                      </div>
                      {s.reason && (
                        <div className="verb-row__meta">
                          <span className="muted">reason: {s.reason}</span>
                        </div>
                      )}
                      {s.output !== undefined && (
                        <CodeBlock value={s.output} />
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>

        <div className="form">
          <div className="form__title">View runs</div>
          <div className="form__actions">
            <Field label="Workflow" hint="See past runs of this workflow.">
              <Select value={runsId} ariaLabel="Workflow" onChange={setRunsId} options={wfOptions} />
            </Field>
            <button className="btn" disabled={runsBusy} onClick={loadRuns}>
              {runsBusy ? "..." : "Load runs"}
            </button>
            {runsError && <span className="error">{runsError}</span>}
          </div>
          {runs && (
            <p className="muted">
              {runs.length === 0 ? "No runs." : `${runs.length} run(s):`}{" "}
              {runs.map((r) => (
                <RunLink runId={r} key={r} />
              ))}
            </p>
          )}
        </div>
      </div>

      <div className="list-card">
        <div className="list-card__head">
          <h3>Workflows</h3>
          <button className="btn" onClick={() => workflows.reload()}>
            Refresh
          </button>
        </div>
        <div className="list-card__body">
          {workflows.loading && !workflows.data && (
            <p className="muted">Loading...</p>
          )}
          {workflows.error && (
            <p className="error">Failed to load: {workflows.error}</p>
          )}
          {!workflows.loading && list.length === 0 && (
            <p className="muted">No workflows yet.</p>
          )}
          {list.map((w) => (
            <div className="row-line" key={`${w.id}@${w.version}`}>
              <div>
                <code>{w.id}</code> <span className="muted">v{w.version}</span>
              </div>
              <div className="kv">
                <span className="badge">{w.source}</span>
                {w.intent_tags.length > 0 && (
                  <span className="muted">{listToCsv(w.intent_tags)}</span>
                )}
              </div>
            </div>
          ))}
        </div>

        <div className="list-card">
          <div className="list-card__head">
            <h3>Verb palette</h3>
            <button className="btn" onClick={() => caps.reload()}>
              Refresh
            </button>
          </div>
          <div className="list-card__body">
            <p className="muted">
              Scoped to this identity. Click a verb to copy its id, then paste it
              as a step <code>action</code> in the definition JSON.
            </p>
            {caps.loading && !caps.data && <p className="muted">Loading...</p>}
            {caps.error && (
              <p className="error">Failed to load: {caps.error}</p>
            )}
            {!caps.loading && !caps.error && verbs.length === 0 && (
              <p className="muted">No verbs visible for this identity.</p>
            )}
            {verbs.map((v) => (
              <button
                className="row-line palette-row"
                key={v.id}
                onClick={() => copyVerb(v.id)}
                title="Copy verb id"
              >
                <div>
                  <code>{v.id}</code>{" "}
                  {v.consequence && (
                    <span className="muted">({v.consequence})</span>
                  )}
                </div>
                <div className="kv">
                  {v.binding && (
                    <span className="badge">{v.binding.target_type}</span>
                  )}
                  <span className="muted">
                    {copiedId === v.id ? "copied" : "copy"}
                  </span>
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// The Workflow Studio wraps the form flow and the canvas behind a view toggle.
// Both speak the identical definition.steps contract, so an author can build a
// workflow visually or by hand and Save either way.
function WorkflowStudio() {
  const [view, setView] = useState<WorkflowView>("form");

  return (
    <div className="stack">
      <div className="subtabs" role="tablist" aria-label="Workflow view">
        <button
          className={`subtab ${view === "form" ? "subtab--active" : ""}`}
          onClick={() => setView("form")}
        >
          Form
        </button>
        <button
          className={`subtab ${view === "canvas" ? "subtab--active" : ""}`}
          onClick={() => setView("canvas")}
        >
          Canvas
        </button>
      </div>
      {view === "form" ? <WorkflowForm /> : <WorkflowCanvas />}
    </div>
  );
}

// --- the panel --------------------------------------------------------------

export function StudioPanel() {
  const identity = useIdentity();
  const [sub, setSub] = useState<StudioTab>("skills");
  const isAuthor = AUTHOR_ROLES.has(identity.role);

  return (
    <section className="panel">
      <PageIntro
        title="Studio"
        lead="Where you compose what agents can do: skills, capability (nouns, verbs and what runs them), adapters, and workflows."
        how="Everything you build here is data, not code. Skills give agents instructions + permissions; Router wires a verb to an adapter or agent; Adapters turn an external service into governed verbs; Workflows chain verbs into a flow."
      />

      {!isAuthor && (
        <p className="notice warn">
          This identity (role: <code>{identity.role}</code>) is not an author
          role, so the server will reject writes here with 403. Authoring
          requires one of: org-admin, department-head, manager, lead,
          integrator.
        </p>
      )}

      <nav className="subtabs" aria-label="Studio sections">
        {STUDIO_TABS.map((t) => (
          <button
            key={t.id}
            className={`subtab ${sub === t.id ? "subtab--active" : ""}`}
            onClick={() => setSub(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {sub === "skills" && <SkillsStudio />}
      {sub === "router" && <RouterStudio />}
      {sub === "adapters" && <AdapterStudio />}
      {sub === "workflows" && <WorkflowStudio />}
    </section>
  );
}
