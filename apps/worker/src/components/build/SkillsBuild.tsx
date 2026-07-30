import { useEffect, useState } from "react";
import type {
  AuthoredDefinitionLifecycleResponse,
  GovernedRouteResponse,
  SkillSummary,
  SpawnResult,
  StatusAck,
  UpsertSkillRequest,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import {
  ExactApprovalFinalizer,
  governedResultReason,
  useExactApprovalFinalizer,
} from "../ExactApprovalFinalizer";
import { Unavailable } from "../Shell";
import { parseObject, resultMessage } from "./result";

type SkillMutation =
  | {
    kind: "upsert";
    body: UpsertSkillRequest;
    selected: SkillSummary | null;
  }
  | {
    kind: "archive" | "restore";
    selected: SkillSummary;
  };

type SkillMutationResult =
  | GovernedRouteResponse<StatusAck>
  | AuthoredDefinitionLifecycleResponse;

function sameRouteInput(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

export function SkillsBuild() {
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [id, setId] = useState("");
  const [version, setVersion] = useState("1");
  const [prompt, setPrompt] = useState("");
  const [grants, setGrants] = useState("");
  const [context, setContext] = useState("{}");
  const [extendsId, setExtendsId] = useState("");
  const [locale, setLocale] = useState("en");
  const [description, setDescription] = useState("");
  const [hydratedExisting, setHydratedExisting] = useState<string | null>(null);
  const [spawnSkill, setSpawnSkill] = useState("");
  const [task, setTask] = useState("");
  const [spawn, setSpawn] = useState<SpawnResult | null>(null);
  const [message, setMessage] = useState("");
  const [lifecycleBusy, setLifecycleBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const hydratedSkill = skills.find((skill) => skill.id === hydratedExisting);
  const spawnDefinition = skills.find((skill) => skill.id === spawnSkill.trim());

  function skillBody(): UpsertSkillRequest {
    return {
      id: id.trim(),
      version: version.trim() || "1",
      prompt_fragment: prompt,
      tool_grants: list(grants),
      context_requirements: parseObject(context, "Context requirements"),
      extends: extendsId.trim() || undefined,
      locale: locale.trim() || "en",
      description: description.trim(),
    };
  }

  const finalizer = useExactApprovalFinalizer<
    SkillMutation,
    SkillMutationResult
  >({
    isCurrent: (input) => {
      if (input.kind === "upsert") {
        try {
          return sameRouteInput(input.body, skillBody())
            && (input.selected?.id ?? null) === hydratedExisting
            && sameRouteInput(input.selected ?? null, hydratedSkill ?? null);
        } catch {
          return false;
        }
      }
      return input.selected.id === hydratedExisting
        && sameRouteInput(input.selected, hydratedSkill ?? null);
    },
    replay: (input, approvalId) => {
      if (input.kind === "upsert") {
        return client.upsertSkill(input.body, approvalId);
      }
      return input.kind === "archive"
        ? client.archiveSkill(input.selected.id, approvalId)
        : client.restoreSkill(input.selected.id, approvalId);
    },
    onApplied: async (_result, input) => {
      await refresh(false);
      if (input.kind === "upsert") {
        setMessage(`Skill ${input.body.id} saved.`);
      } else {
        setMessage(input.kind === "archive"
          ? `Skill ${input.selected.id} archived without deleting its versions.`
          : `Skill ${input.selected.id} restored.`);
      }
    },
    onRefused: (result) => {
      setMessage(governedResultReason(
        result,
        "The approved skill change was refused.",
      ));
    },
    onUncertain: async () => {
      await refresh(false);
      setMessage(
        "Canonical skill state was refreshed; no skill change is inferred.",
      );
    },
  });

  async function refresh(invalidate = true) {
    if (invalidate) finalizer.invalidate();
    try {
      const result = await client.skills();
      setSkills(result.skills);
      if (hydratedExisting) {
        if (result.skills.some((skill) => skill.id === hydratedExisting)) {
          const detail = await client.skill(hydratedExisting);
          setId(detail.skill.id);
          setVersion(detail.skill.version);
          setPrompt(detail.skill.prompt_fragment);
          setGrants(detail.skill.tool_grants.join(", "));
          setContext(JSON.stringify(detail.skill.context_requirements, null, 2));
          setExtendsId(detail.skill.extends ?? "");
          setLocale(detail.skill.locale);
          setDescription(detail.skill.description);
          setHydratedExisting(detail.skill.id);
        } else {
          setHydratedExisting(null);
        }
      }
    } catch {
      setMessage("Skills are unavailable for this identity.");
    }
  }
  useEffect(() => {
    void refresh(false);
  }, []);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setMessage("");
    try {
      const input: SkillMutation = {
        kind: "upsert",
        body: skillBody(),
        selected: hydratedSkill ?? null,
      };
      const result = await client.upsertSkill(input.body);
      if (finalizer.begin(input, result, "Skill definition change")) {
        setMessage("Skill change is waiting for human approval in Inbox.");
        return;
      }
      setMessage(resultMessage(result, `Skill ${id.trim()} saved.`));
      if (result.status === "ok") await refresh(false);
    } catch {
      setMessage("The skill was not changed. Check its identifier, grants and your author role.");
    } finally {
      setSaving(false);
    }
  }

  async function edit(skill: SkillSummary) {
    finalizer.invalidate();
    setMessage("");
    setHydratedExisting(null);
    setSpawnSkill(skill.id);
    try {
      const result = await client.skill(skill.id);
      setId(result.skill.id);
      setVersion(result.skill.version);
      setPrompt(result.skill.prompt_fragment);
      setGrants(result.skill.tool_grants.join(", "));
      setContext(JSON.stringify(result.skill.context_requirements, null, 2));
      setExtendsId(result.skill.extends ?? "");
      setLocale(result.skill.locale);
      setDescription(result.skill.description);
      setHydratedExisting(result.skill.id);
    } catch {
      setMessage("The complete authoring record could not be loaded, so replacement is disabled.");
    }
  }

  function newSkill() {
    finalizer.invalidate();
    setId("");
    setVersion("1");
    setPrompt("");
    setGrants("");
    setContext("{}");
    setExtendsId("");
    setLocale("en");
    setDescription("");
    setHydratedExisting(null);
  }

  async function lifecycle() {
    if (!hydratedSkill) return;
    setLifecycleBusy(true);
    setMessage("");
    try {
      const action = hydratedSkill.is_active ? "archive" : "restore";
      const input: SkillMutation = { kind: action, selected: hydratedSkill };
      const result = input.kind === "archive"
        ? await client.archiveSkill(input.selected.id)
        : await client.restoreSkill(input.selected.id);
      if (finalizer.begin(input, result, `Skill ${action}`)) {
        setMessage(`Skill ${action} is waiting for human approval in Inbox.`);
        return;
      }
      if (result.status === "ok") {
        setMessage(
          action === "archive"
            ? `Skill ${hydratedSkill.id} archived without deleting its versions.`
            : `Skill ${hydratedSkill.id} restored.`,
        );
        await refresh(false);
      } else if (result.status === "pending_human") {
        setMessage(`Skill ${action} is waiting for human approval in Inbox.`);
      } else {
        setMessage(result.reason ?? `Skill ${action} was refused.`);
      }
    } catch {
      setMessage("The skill lifecycle change was unavailable.");
    } finally {
      setLifecycleBusy(false);
    }
  }

  async function test(event: React.FormEvent) {
    event.preventDefault();
    setSpawn(null);
    try {
      const result = await client.testSpawn(spawnSkill.trim(), {
        task: task.trim() || `Test ${spawnSkill.trim()}`,
      });
      setSpawn(result);
      setMessage(
        result.status === "denied"
          ? `Denied: ${result.reason ?? "this identity cannot spawn that skill"}.`
          : "Test spawn completed. Effective grants are shown below.",
      );
    } catch {
      setMessage("The test spawn was unavailable. No alternate runtime was used.");
    }
  }

  return (
    <div className="build-layout">
      <section className="settings-card build-inventory">
        <div className="section-heading"><div><p className="eyebrow">Skill library</p><h2>Approved instruction sets</h2></div><div className="inline-actions"><button className="secondary-button" onClick={newSkill}>New</button><button className="secondary-button" onClick={() => void refresh()}>Refresh</button></div></div>
        {skills.length === 0 ? <Unavailable title="No skills visible">Create a skill if your role has authoring access.</Unavailable> : (
          <div className="data-list compact-list" role="region" aria-label="Visible skills" tabIndex={0}>{skills.map((skill) => (
            <button className="data-row" key={`${skill.id}@${skill.version}`} onClick={() => void edit(skill)}>
              <span className="data-row-copy"><strong>{skill.id}</strong><small>{skill.tool_grants.length} bounded grants · {skill.locale}</small></span>
              <span className="row-meta">{skill.status} · v{skill.version}</span>
            </button>
          ))}</div>
        )}
      </section>
      <div className="build-forms">
        {message && <p className="notice" role="status">{message}</p>}
        <ExactApprovalFinalizer controller={finalizer} />
        <form className="settings-card author-form" onSubmit={(event) => void save(event)}>
          <p className="eyebrow">Skill authoring</p><h2>Create or update a skill</h2>
          <div className="author-grid">
            <label><span>Identifier</span><input className="field-control" required disabled={Boolean(hydratedExisting)} value={id} onChange={(event) => { finalizer.invalidate(); setId(event.target.value); }} /></label>
            <label><span>Version</span><input className="field-control" required disabled={Boolean(hydratedExisting)} value={version} onChange={(event) => { finalizer.invalidate(); setVersion(event.target.value); }} /></label>
          </div>
          <label><span>Description</span><input className="field-control" value={description} onChange={(event) => { finalizer.invalidate(); setDescription(event.target.value); }} /></label>
          <label><span>Prompt fragment</span><textarea className="field-control" rows={6} value={prompt} onChange={(event) => { finalizer.invalidate(); setPrompt(event.target.value); }} /></label>
          <label><span>Tool grant ceiling (comma or newline separated)</span><textarea className="field-control code-field" rows={4} value={grants} onChange={(event) => { finalizer.invalidate(); setGrants(event.target.value); }} /></label>
          <label><span>Context requirements (JSON object)</span><textarea className="field-control code-field" rows={5} value={context} onChange={(event) => { finalizer.invalidate(); setContext(event.target.value); }} /></label>
          <div className="author-grid">
            <label><span>Extends (optional)</span><input className="field-control" value={extendsId} onChange={(event) => { finalizer.invalidate(); setExtendsId(event.target.value); }} /></label>
            <label><span>Locale</span><input className="field-control" value={locale} onChange={(event) => { finalizer.invalidate(); setLocale(event.target.value); }} /></label>
          </div>
          {hydratedExisting && <p className="muted small">Editing the complete server record for {hydratedExisting}; saving replaces that version atomically.</p>}
          <div className="inline-actions">
            <button className="primary-button" disabled={saving || finalizer.busy}>Save skill</button>
            {hydratedSkill && (
              <button
                className="secondary-button"
                type="button"
                disabled={lifecycleBusy || finalizer.busy}
                onClick={() => void lifecycle()}
              >
                {lifecycleBusy
                  ? hydratedSkill.is_active ? "Archiving…" : "Restoring…"
                  : hydratedSkill.is_active ? "Archive skill" : "Restore skill"}
              </button>
            )}
          </div>
        </form>
        <form className="settings-card author-form" onSubmit={(event) => void test(event)}>
          <p className="eyebrow">Grant proof</p><h2>Test-spawn a bounded worker</h2>
          <label><span>Skill identifier</span><input className="field-control" required value={spawnSkill} onChange={(event) => setSpawnSkill(event.target.value)} /></label>
          <label><span>Task</span><input className="field-control" value={task} onChange={(event) => setTask(event.target.value)} /></label>
          <button
            className="primary-button"
            disabled={spawnDefinition?.is_active === false}
            title={spawnDefinition?.is_active === false ? "Restore this skill before testing it" : undefined}
          >
            Test spawn
          </button>
          {spawnDefinition?.is_active === false && (
            <p className="muted small">Archived skills remain editable but cannot be selected for a test spawn.</p>
          )}
          {spawn && (
            <div className="result-receipt">
              <strong>{spawn.status ?? "completed"}</strong>
              <small>Run {spawn.run_id ?? "not issued"} · {spawn.tokens_used ?? 0} tokens</small>
              <div className="skill-list">
                {(spawn.effective_grants ?? []).length === 0
                  ? <span>No effective grants returned</span>
                  : spawn.effective_grants?.map((grant) => <span key={grant}>{grant}</span>)}
              </div>
            </div>
          )}
        </form>
      </div>
    </div>
  );
}

function list(value: string): string[] {
  return value.split(/[,\n]/).map((item) => item.trim()).filter(Boolean);
}
