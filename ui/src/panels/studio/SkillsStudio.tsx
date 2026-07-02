import { useState } from "react";

import { api } from "../../api/client";
import type {
  SkillSummary,
  SkillsResponse,
  SpawnResult,
  StatusAck,
  VerbInfo,
} from "../../api/types";
import { useFetch, type FetchState } from "../../useFetch";
import { CodeBlock, GrantList, csvToList, errText, parseJson } from "../shared";
import { Field, Hint } from "../ux";
import { AckLine } from "./AckLine";

// Create-or-update form for a single skill. The caller passes the visible verbs
// (for the "add a permission" buttons) and a reload callback fired on success.
function SkillUpsertForm({
  verbs,
  onSaved,
}: {
  verbs: VerbInfo[];
  onSaved: () => void;
}) {
  const [id, setId] = useState("");
  const [version, setVersion] = useState("1.0.0");
  const [fragment, setFragment] = useState("");
  const [grants, setGrants] = useState("");
  const [ctxReq, setCtxReq] = useState("{}");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ack, setAck] = useState<StatusAck | null>(null);

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
      if (res.status === "ok") onSaved();
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  function addGrant(id: string) {
    const have = csvToList(grants);
    if (!have.includes(id)) setGrants([...have, id].join(", "));
  }

  return (
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
      {verbs.length > 0 && (
        <div className="kv">
          <span className="ux-hint">Add a permission:</span>
          {verbs.map((v) => (
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
  );
}

// Test spawn: run a skill under the author's own grants and show the child's
// effective_grants as proof it never escalates.
function TestSpawnForm() {
  const [spawnSkill, setSpawnSkill] = useState("");
  const [spawnTask, setSpawnTask] = useState("");
  const [spawnBusy, setSpawnBusy] = useState(false);
  const [spawnError, setSpawnError] = useState<string | null>(null);
  const [spawnResult, setSpawnResult] = useState<SpawnResult | null>(null);

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

  return (
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
  );
}

// The list card down the right rail. It re-reads on demand and on upsert.
function SkillsList({ skills }: { skills: FetchState<SkillsResponse> }) {
  const list: SkillSummary[] = skills.data?.skills ?? [];
  return (
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
  );
}

export function SkillsStudio() {
  const skills = useFetch(() => api.skills(), []);
  const caps = useFetch(() => api.capabilities(), []);
  const allVerbs = caps.data?.verbs ?? [];

  return (
    <div className="cols">
      <div className="stack">
        <SkillUpsertForm verbs={allVerbs} onSaved={() => skills.reload()} />
        <TestSpawnForm />
      </div>
      <SkillsList skills={skills} />
    </div>
  );
}
