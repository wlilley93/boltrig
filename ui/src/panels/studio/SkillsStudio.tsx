import { useState } from "react";

import { api } from "../../api/client";
import type {
  SkillSummary,
  SkillsResponse,
  SpawnResult,
} from "../../api/types";
import { useFetch, type FetchState } from "../../useFetch";
import { CodeBlock, GrantList, errText } from "../shared";
import { SkillUpsertForm } from "./skillsStudio/SkillUpsertForm";

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
