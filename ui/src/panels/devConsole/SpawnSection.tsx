import { useState } from "react";

import { api } from "@/api/client";
import type { SkillsResponse, SpawnRequest, SpawnResult } from "@/api/types";
import type { FetchState } from "@/useFetch";
import { CodeBlock, GrantList, RunLink, csvToList, errText, parseJson } from "@/panels/shared";
import { Field, Hint, InfoCallout } from "@/panels/ux";

export function useSpawn(skillsList: FetchState<SkillsResponse>) {
  const availableSkills = skillsList.data?.skills ?? [];

  const [task, setTask] = useState("");
  const [skills, setSkills] = useState("");
  const [prefer, setPrefer] = useState("");
  const [spawnBusy, setSpawnBusy] = useState(false);
  const [spawnError, setSpawnError] = useState<string | null>(null);
  const [spawnResult, setSpawnResult] = useState<SpawnResult | null>(null);

  function addSkill(id: string) {
    const have = csvToList(skills);
    if (!have.includes(id)) setSkills([...have, id].join(", "));
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

  return {
    availableSkills,
    task,
    setTask,
    skills,
    setSkills,
    prefer,
    setPrefer,
    spawnBusy,
    spawnError,
    spawnResult,
    addSkill,
    spawn,
  };
}

function SkillChips({
  availableSkills,
  addSkill,
}: {
  availableSkills: { id: string }[];
  addSkill: (id: string) => void;
}) {
  if (availableSkills.length === 0) return null;
  return (
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
  );
}

function SpawnResultView({ result }: { result: SpawnResult }) {
  return (
    <div className="stack">
      <div className="row-line">
        <span className="badge">{result.status ?? "?"}</span>
        {result.run_id && <RunLink runId={result.run_id} />}
      </div>
      {result.reason && <p className="error">{result.reason}</p>}
      <div className="row-line">
        <span className="muted">Permissions the agent got</span>
        <GrantList grants={result.effective_grants} />
      </div>
      <CodeBlock value={result} />
    </div>
  );
}

export function SpawnSection({ skillsList }: { skillsList: FetchState<SkillsResponse> }) {
  const {
    availableSkills,
    task,
    setTask,
    skills,
    setSkills,
    prefer,
    setPrefer,
    spawnBusy,
    spawnError,
    spawnResult,
    addSkill,
    spawn,
  } = useSpawn(skillsList);

  return (
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
      <SkillChips availableSkills={availableSkills} addSkill={addSkill} />
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
      {spawnResult ? <SpawnResultView result={spawnResult} /> : <Hint>Run a spawn to see the agent's permissions and result here.</Hint>}
    </div>
  );
}
