import { useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import type { InvokeResult, SkillSummary } from "../api/types";
import { navigate } from "../router";
import { useFetch } from "../useFetch";
import { CardSelect, ChipPicker, JsonDisclosure, SegmentedV2, Stepper } from "./uxForm";
import { GrantList, PendingHumanCard, SaveBar } from "./uxFlow";
import {
  CONSEQUENCE,
  EmptyState,
  FetchError,
  Field,
  InfoCallout,
  PageIntro,
  Select,
  StatusBadge,
  WORK_STATUS,
} from "./ux";
import { apiReason, RunLink } from "./shared";
import {
  budgetPct,
  deniedOf,
  enrichAgents,
  readAgentSpecs,
  readModelEndpoints,
  runtimeOptions,
} from "./agents/model";

interface AgentParams extends Record<string, unknown> {
  name: string;
  runtime: string;
  supported_skills: string[];
  max_depth: number;
  is_ephemeral: boolean;
  cost_tier: string;
  model_endpoint?: string;
}

function toParams(agent: ReturnType<typeof enrichAgents>[number]): AgentParams {
  return {
    name: agent.name,
    runtime: agent.runtime,
    supported_skills: [...agent.supported_skills],
    max_depth: agent.max_depth,
    is_ephemeral: agent.is_ephemeral,
    cost_tier: agent.cost_tier,
    model_endpoint: agent.model_endpoint,
  };
}

function stable(value: unknown): string {
  return JSON.stringify(value);
}

function skillScope(skill: SkillSummary): string {
  const slash = skill.id.indexOf("/");
  return slash > 0 ? skill.id.slice(0, slash) : "skills";
}

function BudgetMeter({
  budget,
}: {
  budget: ReturnType<typeof enrichAgents>[number]["budget"];
}) {
  const pct = budgetPct(budget);
  if (!budget || pct === null) {
    return <span className="muted">No department budget row is visible.</span>;
  }
  const limit =
    budget.token_limit !== null
      ? `${budget.spent_tokens} / ${budget.token_limit} tokens`
      : budget.cost_limit_micros !== null
        ? `$${(budget.spent_micros / 1_000_000).toFixed(2)} / $${(budget.cost_limit_micros / 1_000_000).toFixed(2)}`
        : "no limit";
  return (
    <div className="ag-detail-budget">
      <span className="ag-budget ag-budget--wide">
        <span className="ag-budget__fill" style={{ width: `${pct}%` }} />
      </span>
      <span>
        {limit} this {budget.window}. {budget.hard_stop ? "Hard stop on." : "Soft alert only."}
      </span>
    </div>
  );
}

function classifyResult(result: InvokeResult): string | null {
  if (result.status === "denied" || result.status === "error") return result.reason;
  return null;
}

export function AgentSlide({ agentName }: { agentName: string }) {
  const hierarchy = useFetch(() => api.getConfig("hierarchy"), []);
  const pool = useFetch(() => api.getConfig("ephemeral_runtimes"), []);
  const models = useFetch(() => api.getConfig("models"), []);
  const skills = useFetch(() => api.skills(), []);
  const caps = useFetch(() => api.capabilities(), []);
  const budgets = useFetch(() => api.budgets(), [], 30000);
  const work = useFetch(() => api.work(), [], 30000);

  const denied = deniedOf(hierarchy.data) ?? deniedOf(pool.data);
  const specs = useMemo(
    () => readAgentSpecs(hierarchy.data, pool.data),
    [hierarchy.data, pool.data],
  );
  const agents = useMemo(
    () =>
      enrichAgents(
        specs,
        skills.data?.skills ?? [],
        caps.data?.verbs ?? [],
        budgets.data?.budgets ?? [],
        work.data?.items ?? [],
      ),
    [specs, skills.data, caps.data, budgets.data, work.data],
  );
  const agent = agents.find((a) => a.name === agentName);
  const [saved, setSaved] = useState<AgentParams | null>(null);
  const [draft, setDraft] = useState<AgentParams | null>(null);
  const [jsonText, setJsonText] = useState("");
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<{ id: string; params: AgentParams } | null>(null);

  useEffect(() => {
    if (!agent) return;
    const params = toParams(agent);
    setSaved(params);
    setDraft(params);
    setJsonText(JSON.stringify(params, null, 2));
    setJsonError(null);
    setError(null);
    setPending(null);
  }, [agent?.name]);

  const modelEndpoints = useMemo(() => readModelEndpoints(models.data), [models.data]);
  const runtimes = useMemo(() => runtimeOptions(specs), [specs]);
  const skillOptions = useMemo(() => {
    const allSkills = skills.data?.skills ?? [];
    const groups = [...new Set(allSkills.map((skill) => skillScope(skill)))].sort();
    return [
      { value: "*", label: "All skills", hint: "Match every current and future skill." },
      ...groups.map((group) => ({
        value: `${group}/*`,
        label: `${group}/*`,
        hint: `Match every skill under ${group}.`,
      })),
      ...allSkills.map((skill) => ({
        value: skill.id,
        label: skill.id,
        hint: `${skill.version} / ${skill.tool_grants.length} grant(s)`,
      })),
    ];
  }, [skills.data]);
  const preview = useMemo(() => {
    if (!agent || !draft) return null;
    return enrichAgents(
      [{ ...agent, ...draft }],
      skills.data?.skills ?? [],
      caps.data?.verbs ?? [],
      budgets.data?.budgets ?? [],
      work.data?.items ?? [],
    )[0];
  }, [agent, draft, skills.data, caps.data, budgets.data, work.data]);

  const dirty = draft !== null && saved !== null && stable(draft) !== stable(saved);
  const loading =
    (hierarchy.loading && !hierarchy.data) || (pool.loading && !pool.data);

  function update(next: Partial<AgentParams>) {
    setDraft((current) => {
      if (!current) return current;
      const merged = { ...current, ...next };
      setJsonText(JSON.stringify(merged, null, 2));
      setJsonError(null);
      return merged;
    });
  }

  function updateJson(text: string) {
    setJsonText(text);
    try {
      const parsed = JSON.parse(text) as AgentParams;
      setDraft(parsed);
      setJsonError(null);
    } catch {
      setJsonError("Fix the JSON before requesting a change.");
    }
  }

  async function save() {
    if (!draft || jsonError) return;
    setSaving(true);
    setError(null);
    try {
      const result = await api.invoke({
        noun: "control",
        verb: "control.capability.upsert",
        params: draft,
      });
      if (result.status === "pending_human") {
        setPending({ id: result.hitl_request_id, params: draft });
        return;
      }
      const reason = classifyResult(result);
      if (reason) {
        setError(reason);
        return;
      }
      setSaved(draft);
    } catch (err) {
      setError(apiReason(err));
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <section className="panel ag-detail"><p className="muted">Loading agent...</p></section>;
  }
  if (denied) {
    return (
      <section className="panel ag-detail">
        <PageIntro title="Agents" />
        <InfoCallout tone="warn" title="No access to this agent">
          The server declined the org read ({denied}). Ask an admin to widen
          your access.
        </InfoCallout>
      </section>
    );
  }
  if (!agent || !draft || !preview) {
    return (
      <section className="panel ag-detail">
        <EmptyState
          title="Agent not found"
          body={`No configured agent named ${agentName} is visible to this identity.`}
          action={<button className="btn" onClick={() => navigate("/agents")}>Back to org</button>}
        />
      </section>
    );
  }

  return (
    <section className="panel ag-detail">
      <PageIntro
        title={<><code>{agent.name}</code> <span className="badge">{agent.kind}</span></>}
        lead="Inspect what this agent can do and request governed changes to its live capability profile."
        how="Hierarchy placement is config-backed. Capability profile changes are live for future spawns once the approval is applied."
        actions={<button className="btn" onClick={() => navigate("/agents")}>Back to org</button>}
      />

      <FetchError error={skills.error} status={skills.errorStatus} onRetry={skills.reload} />
      <FetchError error={caps.error} status={caps.errorStatus} onRetry={caps.reload} />

      {(agent.kind === "chief" || agent.kind === "head") && (
        <InfoCallout title="Hierarchy config is read-only here">
          This slide can request a live capability change through the kernel.
          Moving departments or rewriting hierarchy config stays in Admin until
          the org-config verb lands.
        </InfoCallout>
      )}

      <div className="ag-profile">
        <div>
          <span className={`ag-profile__accent ag-profile__accent--${agent.kind}`} />
          <h3><code>{agent.name}</code></h3>
          <p>
            {agent.department ? `${agent.department} department. ` : ""}
            {agent.runtime} runtime, {agent.model_endpoint ?? "default model"},
            depth {agent.max_depth}, {agent.cost_tier} cost tier.
          </p>
        </div>
        <div className="ag-profile__badges">
          <span className="badge">{agent.is_ephemeral ? "ephemeral" : "durable"}</span>
          <span className="badge">{preview.matchedSkills.length} matched skills</span>
          <span className="badge">{preview.effectiveVerbs.length} callable verbs</span>
        </div>
      </div>

      <div className="ag-detail-grid">
        <section className="ag-section">
          <h3>Skills</h3>
          <Field
            label="Skill patterns"
            hint="Patterns like analysis/* include future skills under that path. The preview below shows what matches today."
            meta={`${preview.matchedSkills.length} matches`}
          >
            <ChipPicker
              value={draft.supported_skills}
              onChange={(value) => update({ supported_skills: value })}
              options={skillOptions}
              allowFree
              mono
              ariaLabel="Skill patterns"
              placeholder="Search skills or add a pattern"
              validate={(value) =>
                /^[a-z0-9*][a-z0-9_./*@-]*$/i.test(value)
                  ? null
                  : "Use skill ids or patterns such as analysis/*."
              }
              emptyHint="Choose exact skills or path patterns."
            />
          </Field>
          {preview.effectiveGrants.length > 0 ? (
            <GrantList grants={preview.effectiveGrants} />
          ) : (
            <p className="muted">No grants are matched by the current skill patterns.</p>
          )}
        </section>

        <section className="ag-section">
          <h3>Model and limits</h3>
          <div className="ag-form-grid">
            <Field label="Runtime" hint="The engine that runs this profile.">
              <Select
                value={draft.runtime}
                onChange={(runtime) => update({ runtime })}
                options={runtimes.map((runtime) => ({ value: runtime, label: runtime }))}
              />
            </Field>
            <Field label="Model endpoint" hint="Endpoint id as configured in the manifest.">
              <Select
                value={draft.model_endpoint ?? ""}
                onChange={(model_endpoint) =>
                  update({ model_endpoint: model_endpoint || undefined })
                }
                options={[
                  { value: "", label: "default" },
                  ...modelEndpoints.map((m) => ({
                    value: m.id,
                    label: `${m.id}${m.model ? ` (${m.model})` : ""}`,
                  })),
                ]}
              />
            </Field>
            <Field label="Max depth" hint="How many levels of sub-agents this profile may spawn.">
              <Stepper
                value={draft.max_depth}
                min={1}
                max={5}
                unit="levels"
                onChange={(max_depth) => update({ max_depth })}
              />
            </Field>
            <Field label="Ephemeral" hint="Ephemeral profiles are spawned per task and discarded.">
              <SegmentedV2
                value={draft.is_ephemeral ? "yes" : "no"}
                onChange={(value) => update({ is_ephemeral: value === "yes" })}
                options={[
                  { value: "yes", label: "Yes" },
                  { value: "no", label: "No" },
                ]}
              />
            </Field>
          </div>
          <Field label="Cost tier" hint="Used by routing and cost policy.">
            <CardSelect
              value={draft.cost_tier}
              onChange={(cost_tier) => update({ cost_tier })}
              options={[
                { value: "cheap", label: "Cheap", body: "Lowest-cost bulk work" },
                { value: "standard", label: "Standard", body: "Default balance" },
                { value: "premium", label: "Premium", body: "Strongest model lane" },
              ]}
            />
          </Field>
        </section>

        <section className="ag-section">
          <h3>Fulfils these verbs</h3>
          {preview.boundVerbs.length === 0 ? (
            <p className="muted">No visible verbs are bound directly to this agent.</p>
          ) : (
            <div className="ag-table">
              {preview.boundVerbs.map((verb) => (
                <div className="ag-table__row" key={verb.id}>
                  <code>{verb.id}</code>
                  <span>{verb.noun}</span>
                  <StatusBadge value={verb.consequence} glossary={CONSEQUENCE} />
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="ag-section">
          <h3>Can call</h3>
          {preview.effectiveVerbs.length === 0 ? (
            <p className="muted">No scoped verbs are visible through the matched grants.</p>
          ) : (
            <div className="ag-table">
              {preview.effectiveVerbs.slice(0, 18).map((verb) => (
                <div className="ag-table__row" key={verb.id}>
                  <code>{verb.id}</code>
                  <span>{verb.noun}</span>
                  <StatusBadge value={verb.consequence} glossary={CONSEQUENCE} />
                </div>
              ))}
            </div>
          )}
          <InfoCallout>
            This list is computed with your own scoped capability read. A parent
            can narrow authority further at spawn time.
          </InfoCallout>
        </section>

        <section className="ag-section">
          <h3>Budget</h3>
          <BudgetMeter budget={preview.budget} />
        </section>

        <section className="ag-section">
          <h3>Work</h3>
          {preview.workItems.length === 0 ? (
            <p className="muted">No visible work is owned by this agent's department.</p>
          ) : (
            <div className="ag-table">
              {preview.workItems.slice(0, 8).map((item) => (
                <div className="ag-table__row" key={item.id}>
                  <span>{item.intent}</span>
                  <StatusBadge value={item.status} glossary={WORK_STATUS} />
                  {item.hatchet_run_id ? (
                    <RunLink runId={item.hatchet_run_id} label="run" />
                  ) : (
                    <span className="muted">no run</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      <JsonDisclosure
        value={jsonText}
        onChange={updateJson}
        error={jsonError}
        summaryNote="control.capability.upsert params"
      />
      {jsonError && <InfoCallout tone="warn">{jsonError}</InfoCallout>}
      {error && <InfoCallout tone="warn">{error}</InfoCallout>}
      {pending && (
        <PendingHumanCard
          hitlRequestId={pending.id}
          noun="control"
          verb="control.capability.upsert"
          sentParams={pending.params}
          onApplied={(result) => {
            const reason = classifyResult(result);
            if (reason) {
              setError(reason);
              return;
            }
            setSaved(pending.params);
            setDraft(pending.params);
            setPending(null);
          }}
          onDenied={(reason) => setError(reason)}
        />
      )}
      <SaveBar
        dirty={dirty}
        saving={saving}
        label={<>Unsaved changes to <code>{agent.name}</code></>}
        saveLabel="Save"
        governed
        onSave={() => void save()}
        onDiscard={() => {
          if (!saved) return;
          setDraft(saved);
          setJsonText(JSON.stringify(saved, null, 2));
          setJsonError(null);
          setError(null);
        }}
      />
    </section>
  );
}
