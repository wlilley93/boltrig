// Developer console (Capability plane). Surfaces three client-ready kernel
// endpoints that no other panel exposes: direct verb invoke (POST /v1/invoke),
// ephemeral agent spawn (POST /v1/spawn) and the generated adapter source
// (GET /v1/adapters/{id}/source). Every call is server-authoritative: a denial,
// a pending-human pause or a degraded result is rendered faithfully, exactly as
// the kernel returned it (the AdminPanel pattern). The role gate on the tab is
// cosmetic; the chokepoint is the real gate (a 403 returns a denial body).

import { useState } from "react";

import { api } from "../api/client";
import type { SpawnRequest, SpawnResult } from "../api/types";
import { useFetch } from "../useFetch";
import { CodeBlock, GrantList, RunLink, csvToList, errText, parseJson } from "./shared";
import { Field, Hint, InfoCallout, PageIntro, Select } from "./ux";
import { InvokeSection } from "./devConsole/InvokeSection";

export function DevConsolePanel() {
  // The scoped verb registry powers the invoke picker; the adapter inventory
  // powers the source viewer; the skills list powers the spawn chips. All are
  // caller-scoped server-side.
  const caps = useFetch(() => api.capabilities(), []);
  const adapters = useFetch(() => api.adapters(), []);
  const skillsList = useFetch(() => api.skills(), []);

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

  const adapterRecords = adapters.data?.adapters ?? [];
  const availableSkills = skillsList.data?.skills ?? [];

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

      <InvokeSection caps={caps} />

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
