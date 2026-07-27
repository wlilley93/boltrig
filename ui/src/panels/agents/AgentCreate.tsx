/**
 * NEW AGENT - the character sheet.
 *
 * Codex configures a custom agent as a TOML file: name, description, developer_instructions,
 * and optionally model, model_reasoning_effort, sandbox_mode, mcp_servers, skills.config.
 * Boltrig runs Codex, so those fields are the real substrate and this form is a face over
 * them, not a parallel invention. What it adds is the two things a text file cannot do:
 *
 *   * It tells you the CONSEQUENCE of a setting while you pick it. "read-only" is not a
 *     value in a dropdown, it is the sentence "this agent cannot change your files", and the
 *     form says so at the point of choosing rather than in documentation nobody opens.
 *   * It gives the agent a FACE. The familiar is derived the moment you type a role, so an
 *     agent has an identity before it has ever run - and by the time it appears in the chat
 *     you already recognise it.
 *
 * ONE FORM, NOT A WIZARD. Every field is on one page with sensible defaults, because the
 * common case is "name it, say what it does, save" and a five-step wizard punishes that case
 * to serve the rare one. The sections are collapsible for the rare one.
 */

import { useMemo, useState } from "react";

import { FamiliarDesigner } from "@/familiar/FamiliarDesigner";
import { bandForRole, type Genotype } from "@/familiar/genotype";

/** Mirrors the Codex custom-agent file, plus boltrig's own tenancy fields. Names match the
 *  TOML keys exactly - a form whose field is called "effort" and whose file key is
 *  "model_reasoning_effort" is a translation layer, and translation layers drift. */
export interface AgentDraft {
  name: string;
  description: string;
  developer_instructions: string;
  role: string;
  department: string;
  model: string;
  model_reasoning_effort: "low" | "medium" | "high" | "xhigh" | "max" | "ultra";
  sandbox_mode: "read-only" | "workspace-write" | "danger-full-access";
  cost_tier: "cheap" | "standard" | "expensive";
  max_depth: number;
  is_ephemeral: boolean;
  supported_skills: string[];
  mcp_servers: string[];
  /** null = the familiar is derived from role and id */
  familiar: Partial<Genotype> | null;
}

export const AGENT_DRAFT_DEFAULTS: AgentDraft = {
  name: "",
  description: "",
  developer_instructions: "",
  role: "",
  department: "",
  model: "gpt-5.6",
  model_reasoning_effort: "medium",
  // The safe end of the scale is the default. An agent that can write to the workspace is a
  // decision somebody should have to make on purpose, and a form that defaults to it makes
  // that decision for them silently, every time, for every agent they ever create.
  sandbox_mode: "read-only",
  cost_tier: "standard",
  max_depth: 3,
  is_ephemeral: false,
  supported_skills: [],
  mcp_servers: [],
  familiar: null,
};

/** What each choice actually MEANS, shown next to it. Sourced from the Codex docs rather
 *  than paraphrased, so the guidance in the UI and the guidance in the docs cannot diverge. */
const EFFORT_HELP: Record<AgentDraft["model_reasoning_effort"], string> = {
  low: "Straightforward work where speed matters most.",
  medium: "The balanced default for most agents.",
  high: "Tracing complex logic, checking assumptions, edge cases. Reviewers and security work.",
  xhigh: "Especially demanding reasoning, where the model supports it.",
  max: "Especially demanding reasoning, where the model supports it.",
  ultra: "The deepest reasoning the model offers. Slowest and most expensive.",
};

const SANDBOX_HELP: Record<AgentDraft["sandbox_mode"], string> = {
  "read-only": "Cannot change your files. The right choice for explorers, reviewers and researchers.",
  "workspace-write": "Can edit files in the workspace. Needed to implement a fix.",
  "danger-full-access": "No sandbox. Only for an agent you have a specific reason to trust that far.",
};

const MODEL_HELP: Record<string, string> = {
  "gpt-5.6": "Start here. Strongest for ambiguous, multi-step work needing planning and follow-through.",
  "gpt-5.6-terra": "Faster and cheaper. Good for exploration, read-heavy scans and parallel workers.",
  "gpt-5.4": "Use when a workflow is pinned to 5.4.",
};

export interface AgentCreateProps {
  /** the id the agent will get; the familiar is derived from it, so it must be known here */
  agentId: string;
  value?: AgentDraft;
  onChange?: (draft: AgentDraft) => void;
  onSubmit?: (draft: AgentDraft) => void;
  onCancel?: () => void;
}

export function AgentCreate({ agentId, value, onChange, onSubmit, onCancel }: AgentCreateProps): JSX.Element {
  const [local, setLocal] = useState<AgentDraft>(value ?? AGENT_DRAFT_DEFAULTS);
  const draft = value ?? local;
  const update = (patch: Partial<AgentDraft>) => {
    const next = { ...draft, ...patch };
    setLocal(next);
    onChange?.(next);
  };

  const band = useMemo(() => bandForRole(draft.role), [draft.role]);
  // Required, per the Codex schema: a custom agent file must define all three.
  const ready = draft.name.trim() && draft.description.trim() && draft.developer_instructions.trim();

  return (
    <form
      className="agent-create"
      onSubmit={(e) => {
        e.preventDefault();
        if (ready) onSubmit?.(draft);
      }}
    >
      <div className="agent-create__cols">
        <div className="agent-create__main">
          <fieldset>
            <legend>Identity</legend>
            <label>
              Name
              <input
                value={draft.name}
                onChange={(e) => update({ name: e.target.value })}
                placeholder="pr_explorer"
                required
              />
              <small>How Codex refers to this agent when spawning it.</small>
            </label>
            <label>
              Role
              <input
                value={draft.role}
                onChange={(e) => update({ role: e.target.value })}
                placeholder="reviewer, researcher, builder, guardian, analyst"
              />
              <small>
                {draft.role
                  ? `Reads as “${band}”. Its familiar takes that family.`
                  : "Sets the familiar's shape family, and how the agent is grouped."}
              </small>
            </label>
            <label>
              Department
              <input value={draft.department} onChange={(e) => update({ department: e.target.value })} />
            </label>
            <label>
              Description
              <textarea
                value={draft.description}
                onChange={(e) => update({ description: e.target.value })}
                rows={2}
                placeholder="Read-only codebase explorer for gathering evidence before changes are proposed."
                required
              />
              <small>When should this agent be used. The orchestrator reads this to decide whether to spawn it.</small>
            </label>
          </fieldset>

          <fieldset>
            <legend>Instructions</legend>
            <label>
              Developer instructions
              <textarea
                value={draft.developer_instructions}
                onChange={(e) => update({ developer_instructions: e.target.value })}
                rows={8}
                placeholder={
                  "Stay in exploration mode.\nTrace the real execution path, cite files and symbols, and avoid proposing fixes unless asked.\nPrefer fast search and targeted file reads over broad scans."
                }
                required
              />
              <small>
                The best agents are narrow and opinionated. Give it one job, and instructions that keep it
                from drifting into adjacent work.
              </small>
            </label>
          </fieldset>

          <fieldset>
            <legend>Runtime</legend>
            <label>
              Model
              <select value={draft.model} onChange={(e) => update({ model: e.target.value })}>
                {Object.keys(MODEL_HELP).map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
              <small>{MODEL_HELP[draft.model] ?? ""}</small>
            </label>
            <label>
              Reasoning effort
              <select
                value={draft.model_reasoning_effort}
                onChange={(e) => update({ model_reasoning_effort: e.target.value as AgentDraft["model_reasoning_effort"] })}
              >
                {(Object.keys(EFFORT_HELP) as Array<AgentDraft["model_reasoning_effort"]>).map((k) => (
                  <option key={k} value={k}>{k}</option>
                ))}
              </select>
              <small>{EFFORT_HELP[draft.model_reasoning_effort]}</small>
            </label>
            <label>
              Sandbox
              <select
                value={draft.sandbox_mode}
                onChange={(e) => update({ sandbox_mode: e.target.value as AgentDraft["sandbox_mode"] })}
              >
                {(Object.keys(SANDBOX_HELP) as Array<AgentDraft["sandbox_mode"]>).map((k) => (
                  <option key={k} value={k}>{k}</option>
                ))}
              </select>
              <small className={draft.sandbox_mode === "danger-full-access" ? "is-warning" : undefined}>
                {SANDBOX_HELP[draft.sandbox_mode]}
              </small>
            </label>
            <label>
              Max depth
              <input
                type="number"
                min={1}
                max={8}
                value={draft.max_depth}
                onChange={(e) => update({ max_depth: Number(e.target.value) })}
              />
              <small>How many levels of subagent this agent may spawn beneath itself.</small>
            </label>
            <label className="agent-create__check">
              <input
                type="checkbox"
                checked={draft.is_ephemeral}
                onChange={(e) => update({ is_ephemeral: e.target.checked })}
              />
              Ephemeral: exists for one run, then goes.
            </label>
          </fieldset>
        </div>

        <aside className="agent-create__aside">
          <FamiliarDesigner
            agentId={agentId}
            role={draft.role}
            value={draft.familiar}
            onChange={(familiar) => update({ familiar })}
          />
        </aside>
      </div>

      <footer className="agent-create__foot">
        <button type="button" onClick={onCancel}>Cancel</button>
        <button type="submit" disabled={!ready}>Create agent</button>
        {!ready && <small>Name, description and instructions are required.</small>}
      </footer>
    </form>
  );
}
